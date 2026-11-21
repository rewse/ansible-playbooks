#!/usr/bin/env python3
"""Regression tests for the access rules of the TeslaMate virtual host."""

import base64
import email.message
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

import jinja2

TESLAMATE = pathlib.Path(__file__).resolve().parents[1] / "roles" / "teslamate"
VHOST = TESLAMATE / "templates" / "teslamate.rewse.jp.conf.j2"
GRAFANA_HOSTNAME = "grafana.rewse.jp"
GRAFANA_VHOST = TESLAMATE / "templates" / f"{GRAFANA_HOSTNAME}.conf.j2"
# Module directories of the Apache builds a developer may have locally.
APACHE_MODULE_DIRS = (
    pathlib.Path("/usr/lib/apache2/modules"),
    pathlib.Path("/usr/libexec/apache2"),
)


def vhost() -> str:
    return VHOST.read_text()


def section(text: str, opening: str, closing: str) -> str:
    match = re.search(
        rf"(?ms)^\s*{re.escape(opening)}\s*$(.*?)^\s*{re.escape(closing)}\s*$", text
    )
    if match is None:
        raise AssertionError(f"{opening} not found")
    return match.group(1)


def apache_module_dir() -> pathlib.Path | None:
    return next(
        (d for d in APACHE_MODULE_DIRS if (d / "mod_proxy_http.so").exists()), None
    )


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def start_apache(
    root: pathlib.Path, vhost_text: str, port: int, directives: tuple[str, ...] = ()
) -> subprocess.Popen[str]:
    """Serves vhost_text over plain HTTP on port and waits until it listens."""
    module_dir = apache_module_dir()
    if module_dir is None:
        raise unittest.SkipTest("no Apache proxy modules found")
    vhost = "\n".join(
        line.replace("*:443", f"127.0.0.1:{port}")
        for line in vhost_text.splitlines()
        if not line.strip().startswith(("SSL", "Include "))
    )
    (root / "vhost.conf").write_text(vhost)
    modules = [
        f"LoadModule {name}_module {module_dir}/mod_{name}.so"
        for name in (
            "mpm_prefork",
            "authn_core",
            "authn_file",
            "authz_core",
            "authz_user",
            "auth_basic",
            "headers",
            "log_config",
            "logio",
            "proxy",
            "proxy_http",
            "proxy_wstunnel",
            "remoteip",
            "rewrite",
            "setenvif",
            "unixd",
        )
        if (module_dir / f"mod_{name}.so").exists()
    ]
    config = root / "httpd.conf"
    config.write_text(
        "\n".join(
            [
                *modules,
                f"Define APACHE_LOG_DIR {root}",
                f"DefaultRuntimeDir {root}",
                f"Listen 127.0.0.1:{port}",
                f"PidFile {root}/httpd.pid",
                f"ErrorLog {root}/error.log",
                "ServerName localhost",
                f"DocumentRoot {root}",
                *directives,
                f"Include {root}/vhost.conf",
            ]
        )
        + "\n"
    )
    binary = shutil.which("httpd") or shutil.which("apache2")
    assert binary is not None
    server = subprocess.Popen(
        [binary, "-X", "-f", str(config)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        for _ in range(100):
            if server.poll() is not None:
                raise AssertionError(server.stderr.read() if server.stderr else "")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    return server
            except OSError:
                time.sleep(0.05)
        raise AssertionError("Apache did not start")
    except BaseException:
        stop_apache(server)
        raise


def stop_apache(server: subprocess.Popen[str]) -> None:
    server.terminate()
    server.wait(timeout=10)


class TeslamateVhostAuthTest(unittest.TestCase):
    def test_auth_covers_every_path(self):
        root = section(vhost(), '<Location "/">', "</Location>")
        self.assertRegex(root, r"(?m)^\s*AuthType Basic\s*$")
        self.assertRegex(root, r"(?m)^\s*Require valid-user\s*$")

    def test_auth_is_not_tied_to_one_backend_scheme(self):
        # A <Proxy> section matches only the backend URL it names, which leaves
        # the ws:// worker for the LiveView socket outside it.
        self.assertNotIn("<Proxy", vhost())

    def test_only_the_exact_socket_path_skips_auth(self):
        root = section(vhost(), '<Location "/">', "</Location>")
        any_of = section(root, "<RequireAny>", "</RequireAny>")
        exemptions = re.findall(r"(?m)^\s*Require expr (.+?)\s*$", any_of)
        self.assertEqual(exemptions, ["\"%{REQUEST_URI} == '/live/websocket'\""])
        self.assertNotIn("=~", vhost())

    def test_websocket_is_proxied_only_at_the_socket_path(self):
        self.assertEqual(
            re.findall(r"(?m)^\s*ProxyPass\s+(\S+)\s+ws://", vhost()),
            ["/live/websocket"],
        )


class TeslamateVhostCrossSiteTest(unittest.TestCase):
    def test_rejects_cross_site_writes(self):
        text = vhost()
        self.assertRegex(text, r"(?m)^\s*RewriteEngine on\s*$")
        rule = re.search(
            r"(?m)^\s*RewriteCond %\{REQUEST_METHOD\} !\^\(GET\|HEAD\|OPTIONS\)\$\s*\n"
            r"\s*RewriteCond %\{HTTP:Sec-Fetch-Site\} \^\(cross-site\|same-site\)\$"
            r"\s*\n\s*RewriteRule \^ - \[F\]\s*$",
            text,
        )
        self.assertIsNotNone(rule)

    def test_rejects_cross_site_subresources(self):
        # Only a top-level document navigation from another site or a sibling
        # subdomain gets through; the rule must precede the proxy mapping.
        text = vhost()
        rule = re.search(
            r"(?m)^\s*RewriteCond %\{HTTP:Sec-Fetch-Site\} \^\(cross-site\|same-site\)\$"
            r"\s*\n\s*RewriteCond %\{HTTP:Sec-Fetch-Mode\} !\^navigate\$ \[OR\]"
            r"\s*\n\s*RewriteCond %\{HTTP:Sec-Fetch-Dest\} !\^document\$"
            r"\s*\n\s*RewriteRule \^ - \[F\]\s*$",
            text,
        )
        assert rule is not None
        self.assertLess(rule.start(), text.index("ProxyPass "))

    def test_modules_are_enabled(self):
        tasks = (TESLAMATE / "tasks" / "apache.yml").read_text()
        for module in ("auth_basic", "headers", "rewrite"):
            self.assertRegex(tasks, rf"(?m)^\s*- {module}\s*$")


class TeslamateVhostHeadersTest(unittest.TestCase):
    def test_sets_browser_headers_on_every_response(self):
        headers = dict(
            re.findall(r'(?m)^\s*Header always set (\S+) "([^"]*)"\s*$', vhost())
        )
        self.assertEqual(
            headers,
            {
                "Cross-Origin-Opener-Policy": "same-origin",
                "Cross-Origin-Resource-Policy": "same-origin",
                "Strict-Transport-Security": "max-age=31536000",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "SAMEORIGIN",
            },
        )


def grafana_vhost(port: int) -> str:
    environment = jinja2.Environment(
        loader=jinja2.FileSystemLoader(TESLAMATE / "templates"),
        undefined=jinja2.StrictUndefined,
    )
    return environment.get_template(GRAFANA_VHOST.name).render(
        ansible_managed="Ansible managed",
        teslamate_grafana_hostname=GRAFANA_HOSTNAME,
        teslamate_grafana_port=port,
        teslamate_hostname="teslamate.rewse.jp",
    )


class GrafanaVhostHeadersTest(unittest.TestCase):
    def test_drops_client_forwarded_addresses(self):
        # The unset runs in fixups, after mod_remoteip and before mod_proxy
        # adds the restored address; an early unset would race mod_remoteip.
        text = grafana_vhost(3000)
        for header in ("X-Forwarded-For", "X-Real-IP"):
            with self.subTest(header=header):
                self.assertRegex(text, rf"(?m)^\s*RequestHeader unset {header}\s*$")

    def test_sets_browser_headers_on_every_response(self):
        headers = dict(
            re.findall(
                r'(?m)^\s*Header always set (\S+) "([^"]*)"\s*$', grafana_vhost(3000)
            )
        )
        self.assertEqual(
            headers,
            {
                "Strict-Transport-Security": "max-age=31536000",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "SAMEORIGIN",
            },
        )

    def test_rules_only_deny(self):
        # The vhost's sections replace the server-wide Require lines for the
        # requests they match, so a grant here would reopen what those deny.
        requires = re.findall(r"(?m)^\s*Require (.+?)\s*$", grafana_vhost(3000))
        self.assertTrue(requires)
        self.assertEqual(set(requires), {"all denied"})


class _Backend(http.server.BaseHTTPRequestHandler):
    # Stands in for Grafana, answers every request with 200, and keeps the
    # headers of the last request it received.
    last_headers: ClassVar[email.message.Message | None] = None

    def answer(self) -> None:
        type(self).last_headers = self.headers
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Length", "3")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(b"ok\n")

    do_DELETE = do_GET = do_HEAD = do_POST = do_PUT = answer

    def log_message(self, format, *args):
        pass


@unittest.skipUnless(shutil.which("httpd") or shutil.which("apache2"), "no Apache")
class GrafanaVhostApacheTest(unittest.TestCase):
    # Requests that keep working: the login page and form, a bookmark, a
    # sign-out from Grafana's own menu, dashboard links from TeslaMate (a
    # sibling subdomain) and from other dashboards with their ordinary
    # variables, a bookmark of a dashboard URL Grafana wrote with base_url set
    # to TeslaMate's URL, and the signed-in password change.
    ALLOWED = (
        ("GET", "/login", None),
        ("GET", "/login", "cross-site"),
        ("POST", "/login", "same-origin"),
        ("GET", "/logout", None),
        ("GET", "/logout", "none"),
        ("GET", "/logout", "same-origin"),
        ("GET", "/profile/switch-org/1", "same-origin"),
        ("GET", "/d/kOuP_Fggz/trip?orgId=1&var-car_id=1", "same-site"),
        ("GET", "/d/zm7wN6Zgz/drive-details?var-car_id=1&var-drive_id=5", None),
        ("GET", "/d/x/visited?var-city=Tokyo&var-country_code=JP&var-region=13", None),
        ("GET", "/d/x/charges?var-selected_car_id=1&from=now-7d&to=now", None),
        ("GET", "/d/x/y?var-base_urls=1&var-pg_stat=1&base_url=x", None),
        (
            "GET",
            (
                "/d/FkUpJpQZk/trip?from=now-24h&to=now&timezone=browser"
                "&var-car_id=$__all&var-base_url=https:%2F%2Fteslamate.rewse.jp"
                "&var-from=1789726865169"
            ),
            None,
        ),
        ("GET", "/d/x/y?var-base_url=https://teslamate.rewse.jp", None),
        ("GET", "/d/x/y?var-base_url=https%3A%2F%2Fteslamate.rewse.jp", None),
        ("GET", "/d/x/y?var-car_id=1&x=%zz", None),
        ("GET", "/d/x/y?var-temp_unit=C", None),
        ("GET", "/d/x/y?var-car_id=1&var-temp_unit=F&var-length_unit=km", None),
        ("GET", "/d/x/y?var-temp_unit=C&x=%zz", None),
        ("GET", "/d/x/y?var-temp_units=x&temp_unit=x", None),
        ("GET", "/public/build/img/fav32.png", "cross-site"),
        ("PUT", "/api/user/password", "same-origin"),
        ("GET", "/user/password", None),
    )
    # Sign-out and organization switches another site starts, the password
    # reset pages and endpoints, and URLs that set the variables dashboards
    # use unescaped, in spellings Apache or the browser read the same way.
    REFUSED = (
        ("GET", "/logout", "cross-site"),
        ("GET", "/logout", "same-site"),
        ("GET", "/logout/", "cross-site"),
        ("GET", "/logout?redirectTo=x", "cross-site"),
        ("GET", "//logout", "cross-site"),
        ("GET", "/%6cogout", "cross-site"),
        ("GET", "/./logout", "cross-site"),
        ("GET", "/LOGOUT", "cross-site"),
        ("GET", "/profile/switch-org/2", "cross-site"),
        ("GET", "/profile/switch-org/2", "same-site"),
        ("GET", "//profile//switch-org/2", "cross-site"),
        ("GET", "/profile/switch%2Dorg/2", "cross-site"),
        ("GET", "/user/password/send-reset-email", None),
        ("GET", "/user/password/reset?code=abc", None),
        ("POST", "/api/user/password/send-reset-email", None),
        ("POST", "/api/user/password/reset", None),
        ("POST", "//api//user/password/reset", None),
        ("POST", "/api/user/password/%72eset", None),
        ("POST", "/API/user/password/reset", None),
        ("GET", "/d/x/y?var-base_url=https://example.com", None),
        ("GET", "/d/x/y?orgId=1&var-base_url=https://example.com", "same-origin"),
        ("GET", "/d/x/y?var-base_url", None),
        ("GET", "/d/x/y?var-base_url&orgId=1", None),
        ("GET", "/d/x/y?%76ar-base%5Furl=x", None),
        ("GET", "/d/x/y?var%2Dbase_url=x", None),
        ("GET", "/d/x/y?var-base_url=x&y=%zz", None),
        ("GET", "/d/x/y?var-base_url=https://teslamate.rewse.jp.example.com", None),
        ("GET", "/d/x/y?var-base_url=https://teslamate.rewse.jp@example.com", None),
        ("GET", "/d/x/y?var-base_url=https://teslamateXrewse.jp", None),
        ("GET", "/d/x/y?var-base_url=https://teslamate.rewse.jp/x", None),
        (
            "GET",
            "/d/x/y?var-base_url=https://teslamate.rewse.jp&var-base_url=x",
            None,
        ),
        ("GET", "/d/x/y?y=%00&var-base_url=x", None),
        ("GET", "/d/x/y?var-pg_stat_statements_top_20_mean=x", None),
        ("GET", "/d/x/y?var-pg_stat_statements_enabled=1", None),
        ("GET", "/d/x/y?var-pg%5fstat%5Fstatements_count=1", None),
        ("GET", "/goto/abc?var-base_url=x", None),
        ("GET", "/d/x/y?var-temp_unit=x", None),
        ("GET", "/d/x/y?var-temp_unit=", None),
        ("GET", "/d/x/y?var-temp_unit", None),
        ("GET", "/d/x/y?var-temp_unit&var-car_id=1", None),
        ("GET", "/d/x/y?var-temp_unit=c", None),
        ("GET", "/d/x/y?var-temp_unit=CC", None),
        ("GET", "/d/x/y?var-temp_unit=C,slotlink", None),
        ("GET", "/d/x/y?var-temp_unit=C%20AS%20x", None),
        ("GET", "/d/x/y?var-temp_unit=C;x", None),
        ("GET", "/d/x/y?var-temp_unit=%43", None),
        ("GET", "/d/x/y?var-temp_unit=C&var-temp_unit=x", None),
        ("GET", "/d/x/y?orgId=1&var-temp_unit=F%26x", "same-origin"),
        ("GET", "/d/x/y?%76ar-temp%5Funit=x", None),
        ("GET", "/d/x/y?VAR-TEMP_UNIT=x", None),
        ("GET", "/goto/abc?var-temp_unit=x", None),
        ("GET", "/d-solo/x/y?panelId=1&var-base_url=x", None),
    )

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.backend = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Backend)
        threading.Thread(target=cls.backend.serve_forever, daemon=True).start()
        cls.port = free_port()
        try:
            cls.server = start_apache(
                pathlib.Path(cls.tmp.name),
                grafana_vhost(cls.backend.server_address[1]),
                cls.port,
                (
                    # As behind CloudFront, the client address comes from the
                    # last X-Forwarded-For entry a trusted proxy added.
                    "RemoteIPHeader X-Forwarded-For",
                    "RemoteIPInternalProxy 127.0.0.1",
                ),
            )
        except BaseException:
            cls.backend.shutdown()
            cls.backend.server_close()
            cls.tmp.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        stop_apache(cls.server)
        cls.backend.shutdown()
        cls.backend.server_close()
        cls.tmp.cleanup()

    def request(
        self,
        method: str,
        target: str,
        fetch_site: str | None,
        extra_headers: dict[str, str] | None = None,
    ) -> http.client.HTTPResponse:
        headers = {"Host": GRAFANA_HOSTNAME, **(extra_headers or {})}
        if fetch_site is not None:
            headers["Sec-Fetch-Site"] = fetch_site
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            connection.request(
                method, target, body=b"" if method != "GET" else None, headers=headers
            )
            response = connection.getresponse()
            response.read()
            return response
        finally:
            connection.close()

    def test_ordinary_requests_reach_grafana(self):
        for method, target, fetch_site in self.ALLOWED:
            with self.subTest(method=method, target=target, fetch_site=fetch_site):
                self.assertEqual(self.request(method, target, fetch_site).status, 200)

    def test_refused_requests_answer_403(self):
        for method, target, fetch_site in self.REFUSED:
            with self.subTest(method=method, target=target, fetch_site=fetch_site):
                self.assertEqual(self.request(method, target, fetch_site).status, 403)

    def test_grafana_sees_only_the_restored_client_address(self):
        # Grafana records a session's address from X-Real-IP, or else from the
        # first X-Forwarded-For entry, so neither may carry what a client sent.
        response = self.request(
            "POST",
            "/login",
            "same-origin",
            {
                "X-Forwarded-For": "203.0.113.9, 198.51.100.7",
                "X-Real-IP": "203.0.113.9",
            },
        )
        self.assertEqual(response.status, 200)
        headers = _Backend.last_headers
        assert headers is not None
        self.assertEqual(headers.get_all("X-Forwarded-For"), ["198.51.100.7"])
        self.assertIsNone(headers.get("X-Real-IP"))

    def test_browser_headers_are_on_proxied_and_refused_responses(self):
        for target in ("/login", "/user/password/reset"):
            with self.subTest(target=target):
                response = self.request("GET", target, None)
                self.assertEqual(
                    response.getheader("Strict-Transport-Security"), "max-age=31536000"
                )
                self.assertEqual(
                    response.getheader("X-Content-Type-Options"), "nosniff"
                )
                self.assertEqual(response.getheader("X-Frame-Options"), "SAMEORIGIN")


TESLAMATE_USER = "owner"
TESLAMATE_PASSWORD = "secret"


def teslamate_vhost(port: int, htpasswd: pathlib.Path) -> str:
    environment = jinja2.Environment(
        loader=jinja2.FileSystemLoader(TESLAMATE / "templates"),
        undefined=jinja2.StrictUndefined,
    )
    text = environment.get_template(VHOST.name).render(
        ansible_managed="Ansible managed",
        teslamate_hostname="teslamate.rewse.jp",
        teslamate_port=port,
    )
    return text.replace("/etc/apache2/.teslamate.htpasswd", str(htpasswd))


class _TeslamateBackend(http.server.BaseHTTPRequestHandler):
    # Stands in for TeslaMate: accepts a WebSocket upgrade with 101 and
    # answers every other request with 200.
    def answer(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        if self.headers.get("Upgrade", "").lower() == "websocket":
            self.close_connection = True
            self.send_response(101)
            self.send_header("Connection", "Upgrade")
            self.send_header("Upgrade", "websocket")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", "3")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(b"ok\n")

    do_GET = do_HEAD = do_POST = answer

    def log_message(self, format, *args):
        pass


@unittest.skipUnless(shutil.which("httpd") or shutil.which("apache2"), "no Apache")
@unittest.skipUnless(shutil.which("htpasswd"), "no htpasswd")
class TeslamateVhostApacheTest(unittest.TestCase):
    WEBSOCKET: ClassVar[dict[str, str]] = {
        "Connection": "Upgrade",
        "Sec-WebSocket-Key": base64.b64encode(b"the sample nonce").decode(),
        "Sec-WebSocket-Version": "13",
        "Upgrade": "websocket",
    }
    # Fetch Metadata is (Sec-Fetch-Site, Sec-Fetch-Mode, Sec-Fetch-Dest), or
    # None for a client that sends none of it. Requests that keep working with
    # the credential: clients that are not browsers, bookmarks, links from
    # Grafana dashboards and from other sites, the page's own assets and
    # LiveView calls, and the LiveView socket.
    ALLOWED = (
        ("GET", "/", None, 200),
        ("GET", "/", ("none", "navigate", "document"), 200),
        ("GET", "/drives/1", ("same-site", "navigate", "document"), 200),
        ("GET", "/charges/1", ("cross-site", "navigate", "document"), 200),
        ("GET", "/assets/app.css", ("same-origin", "no-cors", "style"), 200),
        ("GET", "/assets/app.js", ("same-origin", "no-cors", "script"), 200),
        ("GET", "/images/favicon.png", ("same-origin", "no-cors", "image"), 200),
        ("POST", "/drives/1", ("same-origin", "cors", "empty"), 200),
        ("GET", "/live/websocket", ("same-origin", "websocket", "websocket"), 101),
    )
    # Requests another site or a sibling subdomain starts that are not
    # top-level navigations, refused before authentication.
    REFUSED = (
        ("GET", "/drives/1", ("cross-site", "no-cors", "empty")),
        ("GET", "/drives/1", ("same-site", "no-cors", "empty")),
        ("GET", "/geo-fences/1/edit", ("cross-site", "no-cors", "empty")),
        ("GET", "/", ("cross-site", "navigate", "iframe")),
        ("GET", "/", ("same-site", "navigate", "iframe")),
        ("GET", "/", ("cross-site", "cors", "empty")),
        ("GET", "/", ("cross-site", "no-cors", "document")),
        ("GET", "/assets/app.css", ("cross-site", "no-cors", "style")),
        ("GET", "/assets/app.js", ("same-site", "no-cors", "script")),
        ("GET", "/live/websocket", ("cross-site", "websocket", "websocket")),
        ("GET", "/live/websocket", ("same-site", "websocket", "websocket")),
        ("POST", "/drives/1", ("same-site", "navigate", "document")),
    )

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(cls.tmp.name)
        htpasswd = root / "htpasswd"
        subprocess.run(
            ["htpasswd", "-c", "-B", "-i", str(htpasswd), TESLAMATE_USER],
            input=TESLAMATE_PASSWORD,
            text=True,
            check=True,
            capture_output=True,
        )
        cls.backend = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), _TeslamateBackend
        )
        threading.Thread(target=cls.backend.serve_forever, daemon=True).start()
        cls.port = free_port()
        try:
            cls.server = start_apache(
                root, teslamate_vhost(cls.backend.server_address[1], htpasswd), cls.port
            )
        except BaseException:
            cls.backend.shutdown()
            cls.backend.server_close()
            cls.tmp.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        stop_apache(cls.server)
        cls.backend.shutdown()
        cls.backend.server_close()
        cls.tmp.cleanup()

    def request(
        self,
        method: str,
        target: str,
        fetch: tuple[str, str, str] | None,
        authenticated: bool = True,
    ) -> http.client.HTTPResponse:
        headers = {"Host": "teslamate.rewse.jp"}
        if fetch is not None:
            site, mode, dest = fetch
            headers |= {
                "Sec-Fetch-Dest": dest,
                "Sec-Fetch-Mode": mode,
                "Sec-Fetch-Site": site,
            }
            if mode == "websocket":
                headers |= self.WEBSOCKET
        if authenticated:
            token = base64.b64encode(
                f"{TESLAMATE_USER}:{TESLAMATE_PASSWORD}".encode()
            ).decode()
            headers["Authorization"] = f"Basic {token}"
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            connection.request(
                method, target, body=b"" if method != "GET" else None, headers=headers
            )
            response = connection.getresponse()
            response.read()
            return response
        finally:
            connection.close()

    def test_ordinary_requests_reach_teslamate(self):
        for method, target, fetch, status in self.ALLOWED:
            with self.subTest(method=method, target=target, fetch=fetch):
                self.assertEqual(self.request(method, target, fetch).status, status)

    def test_navigations_still_ask_for_the_credential(self):
        for fetch in (None, ("cross-site", "navigate", "document")):
            with self.subTest(fetch=fetch):
                response = self.request("GET", "/", fetch, authenticated=False)
                self.assertEqual(response.status, 401)
                self.assertEqual(
                    response.getheader("WWW-Authenticate"), 'Basic realm="TeslaMate"'
                )

    def test_refused_requests_answer_403_with_or_without_the_credential(self):
        for method, target, fetch in self.REFUSED:
            for authenticated in (False, True):
                with self.subTest(
                    method=method,
                    target=target,
                    fetch=fetch,
                    authenticated=authenticated,
                ):
                    response = self.request(method, target, fetch, authenticated)
                    self.assertEqual(response.status, 403)

    def test_isolation_headers_are_on_every_response(self):
        cases = (
            (None, True),
            (None, False),
            (("cross-site", "no-cors", "empty"), False),
        )
        for fetch, authenticated in cases:
            with self.subTest(fetch=fetch, authenticated=authenticated):
                response = self.request("GET", "/", fetch, authenticated)
                self.assertEqual(
                    response.getheader("Cross-Origin-Opener-Policy"), "same-origin"
                )
                self.assertEqual(
                    response.getheader("Cross-Origin-Resource-Policy"), "same-origin"
                )


if __name__ == "__main__":
    unittest.main()
