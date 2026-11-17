#!/usr/bin/env python3
"""Regression tests for the Home Assistant virtual host."""

import base64
import http.client
import http.server
import pathlib
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from typing import ClassVar

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
VHOST = REPO_ROOT / "roles" / "homeassistant" / "files" / "hass.rewse.jp.conf"
SECONDARY_APACHE = (
    REPO_ROOT / "roles" / "homeassistant_ha_secondary" / "tasks" / "apache.yml"
)
TESLA_KEY_PATH = "/.well-known/appspecific/com.tesla.3p.public-key.pem"
TESLA_KEY_FILE = "/srv/www/tesla/com.tesla.3p.public-key.pem"
# Module directories of the Apache builds a developer may have locally.
APACHE_MODULE_DIRS = (
    pathlib.Path("/usr/lib/apache2/modules"),
    pathlib.Path("/usr/libexec/apache2"),
)
BROWSER_HEADERS = {
    "Referrer-Policy": "no-referrer",
    "Strict-Transport-Security": "max-age=31536000",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
}
# Home Assistant sets these on its own responses.
BACKEND_HEADERS = {
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
}


def vhost() -> str:
    return VHOST.read_text()


def directive_lines(prefix: str) -> list[str]:
    return [
        line.strip() for line in vhost().splitlines() if line.strip().startswith(prefix)
    ]


class HomeAssistantVhostHeadersTest(unittest.TestCase):
    def test_sets_browser_headers_on_every_response(self):
        headers = dict(
            re.findall(r'(?m)^\s*Header always set (\S+) "([^"]*)"\s*$', vhost())
        )
        self.assertEqual(headers, BROWSER_HEADERS)

    def test_drops_the_backend_copy_of_each_header_it_sets(self):
        # Home Assistant's copy is in the onsuccess table and the vhost's in
        # the always table, so without the unset a response carries both.
        unset = directive_lines("Header unset ")
        for header in BACKEND_HEADERS:
            with self.subTest(header=header):
                self.assertIn(f"Header unset {header}", unset)

    def test_secondary_deploys_the_same_file(self):
        self.assertIn(
            "../homeassistant/files/hass.rewse.jp.conf", SECONDARY_APACHE.read_text()
        )


class HomeAssistantVhostFrigateNotificationTest(unittest.TestCase):
    def test_notification_proxy_is_refused_before_the_proxy_rules(self):
        text = vhost()
        refusal = re.search(
            r"(?m)^\s*RewriteRule \^/api/frigate/\(\?:\.\+/\)\?notifications/ - \[F,NC\]\s*$",
            text,
        )
        self.assertIsNotNone(refusal)
        assert refusal is not None
        proxy = re.search(r"(?m)^\s*RewriteRule .*\[P,L\]\s*$", text)
        assert proxy is not None
        self.assertLess(refusal.start(), proxy.start())


class _HomeAssistantStub(http.server.BaseHTTPRequestHandler):
    # Answers like Home Assistant as far as the vhost cares: every response
    # carries its browser headers, /missing answers 404, and a WebSocket
    # upgrade is accepted and echoes what the client sends next.
    protocol_version = "HTTP/1.1"
    paths: ClassVar[list[str]] = []

    def answer(self) -> None:
        type(self).paths.append(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        if (self.headers.get("Upgrade") or "").lower() == "websocket":
            self.send_response(101)
            self.send_header("Connection", "Upgrade")
            self.send_header("Upgrade", "websocket")
            self.end_headers()
            self.wfile.flush()
            self.wfile.write(self.rfile.read(4))
            self.wfile.flush()
            self.close_connection = True
            return
        self.send_response(404 if self.path == "/missing" else 200)
        for name, value in BACKEND_HEADERS.items():
            self.send_header(name, value)
        self.send_header("Content-Length", "3")
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(b"ok\n")
        self.close_connection = True

    do_DELETE = do_GET = do_HEAD = do_POST = do_PUT = answer

    def log_message(self, format, *args):
        pass


@unittest.skipUnless(shutil.which("httpd") or shutil.which("apache2"), "no Apache")
class HomeAssistantVhostApacheTest(unittest.TestCase):
    MODULES = (
        "mpm_prefork",
        "alias",
        "authz_core",
        "headers",
        "proxy",
        "proxy_http",
        "proxy_wstunnel",
        "rewrite",
        "unixd",
    )
    # Paths the Frigate integration serves to signed-in clients only.
    ALLOWED = (
        "/",
        "/api/frigate/frigate/clips/front-1.mp4",
        "/api/frigate/frigate/snapshot/1700000000.000000-abcdef",
        "/api/frigate/frigate/thumbnail/1700000000.000000-abcdef",
        "/api/frigate/snapshot/1700000000.000000-abcdef",
        "/api/frigate/vod/front/start/1/end/2/index.m3u8",
        "/api/states",
        "/lovelace/0",
    )
    # The integration's unauthenticated notification proxy, with and without
    # an instance ID, in spellings Apache reads the same way.
    REFUSED = (
        "/api/frigate/notifications/1700000000.000000-abcdef/snapshot.jpg",
        "/api/frigate/notifications/1700000000.000000-abcdef/thumbnail.jpg",
        "/api/frigate/frigate/notifications/1700000000.000000-abcdef/clip.mp4",
        "/api/frigate/a/b/notifications/1700000000.000000-abcdef/review_preview.gif",
        "/api/frigate/notifications/x/master.m3u8",
        "/api/frigate/%6Eotifications/x/snapshot.jpg",
        "/api/frigate/./notifications/x/snapshot.jpg",
        "//api//frigate/notifications/x/snapshot.jpg",
        "/api/Frigate/Notifications/x/snapshot.jpg",
    )

    @classmethod
    def setUpClass(cls):
        module_dir = next(
            (d for d in APACHE_MODULE_DIRS if (d / "mod_proxy_wstunnel.so").exists()),
            None,
        )
        if module_dir is None:
            raise unittest.SkipTest("no Apache proxy modules found")
        cls.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(cls.tmp.name)
        key = root / "public-key.pem"
        key.write_text("-----BEGIN PUBLIC KEY-----\n")
        cls.backend = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), _HomeAssistantStub
        )
        threading.Thread(target=cls.backend.serve_forever, daemon=True).start()
        backend = f"127.0.0.1:{cls.backend.server_address[1]}"
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            cls.port = probe.getsockname()[1]
        text = "\n".join(
            line.replace("*:443", f"127.0.0.1:{cls.port}")
            .replace("localhost:8123", backend)
            .replace(TESLA_KEY_FILE, str(key))
            for line in vhost().splitlines()
            if not line.strip().startswith(("SSL", "Include "))
        )
        (root / "vhost.conf").write_text(text)
        modules = [
            f"LoadModule {name}_module {module_dir}/mod_{name}.so"
            for name in cls.MODULES
            if (module_dir / f"mod_{name}.so").exists()
        ]
        config = root / "httpd.conf"
        config.write_text(
            "\n".join(
                [
                    *modules,
                    f"DefaultRuntimeDir {root}",
                    f"Listen 127.0.0.1:{cls.port}",
                    f"PidFile {root}/httpd.pid",
                    f"ErrorLog {root}/error.log",
                    "ServerName localhost",
                    f"DocumentRoot {root}",
                    f'<Directory "{root}">',
                    "    Require all granted",
                    "</Directory>",
                    f"Include {root}/vhost.conf",
                ]
            )
            + "\n"
        )
        binary = shutil.which("httpd") or shutil.which("apache2")
        assert binary is not None
        cls.server = subprocess.Popen(
            [binary, "-X", "-f", str(config)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            for _ in range(100):
                if cls.server.poll() is not None:
                    raise AssertionError(
                        cls.server.stderr.read() if cls.server.stderr else ""
                    )
                try:
                    with socket.create_connection(("127.0.0.1", cls.port), timeout=1):
                        return
                except OSError:
                    time.sleep(0.05)
            raise AssertionError("Apache did not start")
        except BaseException:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.server.terminate()
        cls.server.wait(timeout=10)
        cls.backend.shutdown()
        cls.backend.server_close()
        cls.tmp.cleanup()

    def request(self, target: str) -> http.client.HTTPResponse:
        # Apache runs as one process, so a kept-alive connection would hold it
        # until the next request times out.
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            connection.request(
                "GET", target, headers={"Connection": "close", "Host": "hass.rewse.jp"}
            )
            response = connection.getresponse()
            response.read()
            return response
        finally:
            connection.close()

    def upgrade(self, target: str) -> tuple[bytes, bytes]:
        # Returns the status line of the handshake and what came back after it.
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as client:
            client.sendall(
                (
                    f"GET {target} HTTP/1.1\r\n"
                    "Host: hass.rewse.jp\r\n"
                    "Connection: Upgrade\r\n"
                    "Upgrade: websocket\r\n"
                    "Sec-WebSocket-Version: 13\r\n"
                    f"Sec-WebSocket-Key: {base64.b64encode(bytes(16)).decode()}\r\n"
                    "\r\n"
                ).encode()
            )
            received = b""
            while b"\r\n\r\n" not in received:
                chunk = client.recv(4096)
                if not chunk:
                    break
                received += chunk
            head, _, rest = received.partition(b"\r\n\r\n")
            if not head.startswith(b"HTTP/1.1 101"):
                return head.split(b"\r\n")[0], b""
            client.sendall(b"ping")
            while len(rest) < 4:
                chunk = client.recv(4096)
                if not chunk:
                    break
                rest += chunk
            return head.split(b"\r\n")[0], rest

    def test_ordinary_paths_reach_home_assistant(self):
        for target in self.ALLOWED:
            with self.subTest(target=target):
                self.assertEqual(self.request(target).status, 200)

    def test_notification_proxy_is_refused(self):
        for target in self.REFUSED:
            with self.subTest(target=target):
                _HomeAssistantStub.paths.clear()
                self.assertEqual(self.request(target).status, 403)
                self.assertEqual(_HomeAssistantStub.paths, [])

    def test_notification_proxy_upgrade_is_refused(self):
        status, _ = self.upgrade("/api/frigate/notifications/x/snapshot.jpg")
        self.assertTrue(status.startswith(b"HTTP/1.1 403"), status)

    def test_websocket_reaches_home_assistant(self):
        status, echoed = self.upgrade("/api/websocket")
        self.assertTrue(status.startswith(b"HTTP/1.1 101"), status)
        self.assertEqual(echoed, b"ping")

    def test_tesla_public_key_is_served_from_disk(self):
        _HomeAssistantStub.paths.clear()
        response = self.request(TESLA_KEY_PATH)
        self.assertEqual(response.status, 200)
        self.assertEqual(_HomeAssistantStub.paths, [])

    def test_browser_headers_appear_once_on_every_response(self):
        for target, status in (
            ("/", 200),
            ("/missing", 404),
            (self.REFUSED[0], 403),
            (TESLA_KEY_PATH, 200),
        ):
            with self.subTest(target=target):
                response = self.request(target)
                self.assertEqual(response.status, status)
                for name, value in BROWSER_HEADERS.items():
                    self.assertEqual(response.msg.get_all(name), [value], name)


if __name__ == "__main__":
    unittest.main()
