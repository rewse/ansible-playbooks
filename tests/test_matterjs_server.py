#!/usr/bin/env python3
"""Contract tests for the matterjs_server role."""

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

import jinja2
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROLE = REPO_ROOT / "roles" / "matterjs_server"
# Module directories of the Apache builds a developer may have locally.
APACHE_MODULE_DIRS = (
    pathlib.Path("/usr/lib/apache2/modules"),
    pathlib.Path("/usr/libexec/apache2"),
)

NETWORKS = {
    "aws_private_ipv4": "10.0.0.0/16",
    "aws_public_ipv6": "2001:db8:aa::/56",
    "home_private_ipv4": "192.168.0.0/24",
    "home_private_ipv6": "fd00:db8::/64",
    "home_public_ipv4": "192.0.2.9/32",
    "home_public_ipv6": "2001:db8:bb::/64",
    "office_public_ipv4": ["198.51.100.0/24", "203.0.113.0/24"],
}


def role_vars() -> dict:
    return yaml.safe_load((ROLE / "vars" / "main.yml").read_text())


def load_tasks(name: str) -> list[dict]:
    return yaml.safe_load((ROLE / "tasks" / name).read_text())


def render(name: str, **overrides) -> str:
    environment = jinja2.Environment(
        loader=jinja2.FileSystemLoader(ROLE / "templates"),
        undefined=jinja2.StrictUndefined,
    )
    environment.filters["comment"] = lambda text: f"#\n# {text}\n#"
    context = {
        **role_vars(),
        "__matterjs_server_image": {
            "ref": "ghcr.io/matter-js/matterjs-server:1.5.5@sha256:" + "0" * 64
        },
        "ansible_managed": "Ansible managed",
        "networks": NETWORKS,
    }
    context.update(overrides)
    return environment.get_template(name).render(**context)


def handlers(role: pathlib.Path) -> dict:
    return {
        h["name"]: h
        for h in yaml.safe_load((role / "handlers" / "main.yml").read_text())
    }


class MatterjsServerRoleTest(unittest.TestCase):
    def test_ping_is_open_to_every_group(self):
        conf = (ROLE / "files" / "60-matterjs-server-ping.conf").read_text()
        self.assertRegex(conf, r"(?m)^net\.ipv4\.ping_group_range = 0 2147483647$")

    def test_sysctl_reload_matches_the_raspberrypi_role(self):
        theirs = handlers(REPO_ROOT / "roles" / "raspberrypi")
        self.assertEqual(handlers(ROLE)["Reload sysctl"], theirs["Reload sysctl"])

    def test_sysctl_drop_in_notifies_the_reload(self):
        task = load_tasks("sysctl.yml")[0]
        self.assertEqual(task["ansible.builtin.copy"]["dest"], "/etc/sysctl.d")
        self.assertEqual(task["notify"], "Reload sysctl")

    def test_sysctl_is_the_first_component(self):
        first = load_tasks("main.yml")[0]
        self.assertEqual(first["ansible.builtin.import_tasks"], "sysctl.yml")
        self.assertEqual(first["tags"], ["matterjs_server_sysctl"])


def compose() -> dict:
    return yaml.safe_load(render("compose.yaml.j2"))["services"]["matterjs-server"]


class MatterjsServerContainerTest(unittest.TestCase):
    def test_compose_project_and_service(self):
        project = yaml.safe_load(render("compose.yaml.j2"))
        self.assertEqual(project["name"], "matterjs_server")
        service = project["services"]["matterjs-server"]
        self.assertEqual(service["container_name"], "matterjs-server")
        self.assertEqual(service["network_mode"], "host")
        self.assertEqual(service["restart"], "unless-stopped")
        self.assertEqual(service["volumes"], ["/srv/matterjs_server/data:/data"])
        self.assertTrue(
            service["image"].startswith("ghcr.io/matter-js/matterjs-server:")
        )

    def test_environment_is_exactly_the_three_settings(self):
        self.assertEqual(
            compose()["environment"],
            {
                "LISTEN_ADDRESS": "127.0.0.1,::1",
                "PRIMARY_INTERFACE": "eth0",
                "PRODUCTION_MODE": "true",
            },
        )

    def test_no_bluetooth_or_extra_privileges(self):
        service = compose()
        for key in ("cap_add", "privileged", "user"):
            self.assertNotIn(key, service)
        self.assertNotIn("/run/dbus", render("compose.yaml.j2"))

    def test_runs_without_capabilities_or_privilege_gain(self):
        # The image runs as an unprivileged user, and host networking alone
        # lets it listen on loopback and use mDNS on the primary interface.
        service = compose()
        self.assertEqual(service["cap_drop"], ["ALL"])
        self.assertEqual(service["security_opt"], ["no-new-privileges:true"])

    def test_start_is_guarded_by_migrated_or_python_data(self):
        tasks = {t["name"]: t for t in load_tasks("container.yml")}
        stats = {
            t["ansible.builtin.stat"]["path"]
            for t in tasks.values()
            if "ansible.builtin.stat" in t
        }
        self.assertLessEqual(
            {
                "{{ matterjs_server_data_dir }}/chip.json",
                "{{ matterjs_server_data_dir }}/server",
            },
            stats,
        )
        fail = tasks["container | Fail without data to migrate"]
        report = tasks["container | Report skipped start without data"]
        start = tasks["container | Start containers"]
        self.assertIn("not ansible_check_mode", str(fail["when"]))
        self.assertIn("ansible_check_mode", str(report["when"]))
        self.assertIn("__matterjs_server_chip.stat.exists", str(start["when"]))
        self.assertIn("__matterjs_server_storage.stat.exists", str(start["when"]))

    def test_data_directory_is_owned_by_the_container_user(self):
        task = next(
            t["ansible.builtin.file"]
            for t in load_tasks("container.yml")
            if t.get("ansible.builtin.file", {}).get("path")
            == "{{ matterjs_server_data_dir }}"
        )
        self.assertEqual(
            (task["owner"], task["group"], task["mode"]), (1000, 1000, "0700")
        )
        self.assertNotIn("recurse", task)

    def test_legacy_removal_keeps_python_data(self):
        self.assertNotIn(
            "/srv/matter_server", (ROLE / "tasks" / "container.yml").read_text()
        )
        tasks = load_tasks("container.yml")
        removed = [
            t["ansible.builtin.file"]["path"]
            for t in tasks
            if t.get("ansible.builtin.file", {}).get("state") == "absent"
        ]
        self.assertEqual(removed, ["/etc/compose/matter_server"])
        down = next(
            t["community.docker.docker_compose_v2"]
            for t in tasks
            if t.get("community.docker.docker_compose_v2", {}).get("state") == "absent"
        )
        self.assertEqual(down["project_src"], "/etc/compose/matter_server")

    def test_legacy_server_stops_before_the_new_one_starts(self):
        # Both servers would act as the same controller on the same fabric.
        names = [t["name"] for t in load_tasks("container.yml")]
        self.assertLess(
            names.index("container | Remove legacy compose project"),
            names.index("container | Start containers"),
        )

    def test_container_is_an_update_component(self):
        imports = {
            t["ansible.builtin.import_tasks"]: t["tags"] for t in load_tasks("main.yml")
        }
        self.assertEqual(
            imports["container.yml"], ["matterjs_server_container", "update"]
        )


class MatterjsServerApacheTest(unittest.TestCase):
    def test_websocket_is_proxied_before_the_dashboard(self):
        vhost = render("matter.rewse.jp.conf.j2")
        self.assertIn("ServerName matter.rewse.jp", vhost)
        self.assertLess(
            vhost.index("ProxyPass /ws ws://127.0.0.1:5580/ws"),
            vhost.index("ProxyPass / http://127.0.0.1:5580/"),
        )

    def test_only_home_and_vpn_may_connect(self):
        vhost = render("matter.rewse.jp.conf.j2")
        allowed = re.findall(r"(?m)^\s*Require ip (\S+)$", vhost)
        self.assertEqual(
            sorted(allowed),
            sorted(
                [
                    "127.0.0.1",
                    "::1",
                    NETWORKS["home_private_ipv4"],
                    NETWORKS["home_private_ipv6"],
                    NETWORKS["home_public_ipv4"],
                    NETWORKS["home_public_ipv6"],
                    NETWORKS["aws_private_ipv4"],
                    NETWORKS["aws_public_ipv6"],
                ]
            ),
        )
        self.assertNotIn("Require all granted", vhost)
        for office in NETWORKS["office_public_ipv4"]:
            self.assertNotIn(office, vhost)

    def test_vhost_uses_the_wildcard_certificate(self):
        vhost = render("matter.rewse.jp.conf.j2")
        self.assertIn(
            "SSLCertificateFile /etc/letsencrypt/live/rewse.jp/fullchain.pem", vhost
        )
        self.assertIn(
            "SSLCertificateKeyFile /etc/letsencrypt/live/rewse.jp/privkey.pem", vhost
        )

    def test_apache_reload_matches_the_httpd_role(self):
        theirs = handlers(REPO_ROOT / "roles" / "httpd")
        self.assertEqual(handlers(ROLE)["Reload Apache"], theirs["Reload Apache"])

    def test_components_and_dependencies(self):
        imports = [t["ansible.builtin.import_tasks"] for t in load_tasks("main.yml")]
        self.assertEqual(imports, ["sysctl.yml", "container.yml", "apache.yml"])
        meta = yaml.safe_load((ROLE / "meta" / "main.yml").read_text())
        self.assertEqual([d["role"] for d in meta["dependencies"]], ["docker", "httpd"])

    def test_websocket_requires_the_dashboard_origin(self):
        vhost = render("matter.rewse.jp.conf.j2")
        rule = re.search(
            r"(?m)^\s*RewriteEngine on\s*\n"
            r"\s*RewriteCond %\{HTTP:Origin\} !=https://matter\.rewse\.jp\s*\n"
            r"\s*RewriteRule \^/ws - \[F\]\s*$",
            vhost,
        )
        self.assertIsNotNone(rule)


class _MatterServerStub(http.server.BaseHTTPRequestHandler):
    # Answers like matterjs-server as far as the vhost cares: a WebSocket
    # upgrade is accepted and echoes what the client sends next, and any other
    # request answers 200. It records each path it receives.
    protocol_version = "HTTP/1.1"
    paths: ClassVar[list[str]] = []

    def do_GET(self) -> None:
        type(self).paths.append(self.path)
        if (self.headers.get("Upgrade") or "").lower() == "websocket":
            self.send_response(101)
            self.send_header("Connection", "Upgrade")
            self.send_header("Upgrade", "websocket")
            self.end_headers()
            self.wfile.flush()
            self.wfile.write(self.rfile.read(4))
            self.wfile.flush()
        else:
            self.send_response(200)
            self.send_header("Content-Length", "3")
            self.end_headers()
            self.wfile.write(b"ok\n")
        self.close_connection = True

    def log_message(self, format, *args):
        pass


@unittest.skipUnless(shutil.which("httpd") or shutil.which("apache2"), "no Apache")
class MatterjsServerVhostApacheTest(unittest.TestCase):
    MODULES = (
        "mpm_prefork",
        "authz_core",
        "authz_host",
        "proxy",
        "proxy_http",
        "proxy_wstunnel",
        "rewrite",
        "unixd",
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
        cls.backend = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), _MatterServerStub
        )
        threading.Thread(target=cls.backend.serve_forever, daemon=True).start()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            cls.port = probe.getsockname()[1]
        vhost = "\n".join(
            line.replace("*:443", f"127.0.0.1:{cls.port}")
            for line in render(
                "matter.rewse.jp.conf.j2",
                matterjs_server_port=cls.backend.server_address[1],
            ).splitlines()
            if not line.strip().startswith(("SSL", "Include "))
        )
        (root / "vhost.conf").write_text(vhost)
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

    def upgrade(self, target: str, origin: str | None) -> tuple[bytes, bytes]:
        # Returns the status line of the handshake and what came back after it.
        lines = [
            f"GET {target} HTTP/1.1",
            "Host: matter.rewse.jp",
            "Connection: Upgrade",
            "Upgrade: websocket",
            "Sec-WebSocket-Version: 13",
            f"Sec-WebSocket-Key: {base64.b64encode(bytes(16)).decode()}",
        ]
        if origin is not None:
            lines.append(f"Origin: {origin}")
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as client:
            client.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
            received = b""
            while b"\r\n\r\n" not in received:
                chunk = client.recv(4096)
                if not chunk:
                    break
                received += chunk
            head, _, rest = received.partition(b"\r\n\r\n")
            status = head.split(b"\r\n")[0]
            if not status.startswith(b"HTTP/1.1 101"):
                return status, b""
            client.sendall(b"ping")
            while len(rest) < 4:
                chunk = client.recv(4096)
                if not chunk:
                    break
                rest += chunk
            return status, rest

    def test_dashboard_origin_reaches_the_websocket(self):
        status, echoed = self.upgrade("/ws", "https://matter.rewse.jp")
        self.assertTrue(status.startswith(b"HTTP/1.1 101"), status)
        self.assertEqual(echoed, b"ping")

    def test_other_origins_are_refused(self):
        for target, origin in (
            ("/ws", None),
            ("/ws", "https://example.com"),
            ("/ws", "null"),
            ("/ws", "http://matter.rewse.jp"),
            ("/ws", "https://matter.rewse.jp.example.com"),
            ("/ws", "https://matter.rewse.jp:443"),
            ("/ws", "https://nas.rewse.jp"),
            ("/ws/", "https://example.com"),
            ("//ws", "https://example.com"),
            ("/%77s", "https://example.com"),
            ("/./ws", "https://example.com"),
        ):
            with self.subTest(target=target, origin=origin):
                _MatterServerStub.paths.clear()
                status, _ = self.upgrade(target, origin)
                self.assertTrue(status.startswith(b"HTTP/1.1 403"), status)
                self.assertEqual(_MatterServerStub.paths, [])

    def test_dashboard_page_needs_no_origin(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            connection.request(
                "GET", "/", headers={"Connection": "close", "Host": "matter.rewse.jp"}
            )
            self.assertEqual(connection.getresponse().status, 200)
        finally:
            connection.close()


class MatterjsServerWiringTest(unittest.TestCase):
    def test_home_primary_runs_matterjs_server(self):
        play = yaml.safe_load((REPO_ROOT / "home-primary.yml").read_text())[0]
        roles = [r["role"] for r in play["roles"]]
        self.assertIn("matterjs_server", roles)
        self.assertNotIn("matter_server", roles)

    def test_homeassistant_depends_on_matterjs_server(self):
        meta = yaml.safe_load(
            (REPO_ROOT / "roles" / "homeassistant" / "meta" / "main.yml").read_text()
        )
        deps = [d["role"] for d in meta["dependencies"]]
        self.assertIn("matterjs_server", deps)
        self.assertNotIn("matter_server", deps)

    def test_python_matter_server_role_is_gone(self):
        self.assertFalse((REPO_ROOT / "roles" / "matter_server").exists())


if __name__ == "__main__":
    unittest.main()
