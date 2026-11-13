#!/usr/bin/env python3
"""Regression tests for services the internet reaches through Apache."""

import configparser
import http.client
import importlib.util
import pathlib
import re
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
from typing import ClassVar

import jinja2
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROLES = REPO_ROOT / "roles"
# Module directories of the Apache builds a developer may have locally.
APACHE_MODULE_DIRS = (
    pathlib.Path("/usr/lib/apache2/modules"),
    pathlib.Path("/usr/libexec/apache2"),
)
COUCHDB = ROLES / "couchdb"
FAIL2BAN = ROLES / "fail2ban"
LITELLM = ROLES / "litellm"
FILEBROWSER = ROLES / "filebrowser"
HTTPD = ROLES / "httpd"
HOMEASSISTANT = ROLES / "homeassistant"
NVR = ROLES / "nvr"
POSTFIX_CLIENT = ROLES / "postfix_client"
SECONDARY = ROLES / "homeassistant_ha_secondary"
TESLAMATE = ROLES / "teslamate"
UDM = ROLES / "udm"
ZABBIX_SERVER = ROLES / "zabbix_server"


def load_yaml(path: pathlib.Path):
    return yaml.safe_load(path.read_text())


def jail(path: pathlib.Path, section: str) -> configparser.SectionProxy:
    parser = configparser.ConfigParser(interpolation=None)
    lines = [
        line
        for line in path.read_text().splitlines()
        if not line.lstrip().startswith(("#", "{{"))
    ]
    parser.read_string("\n".join(lines))
    return parser[section]


def filter_regex(path: pathlib.Path, variable: str, hostname: str) -> re.Pattern:
    text = path.read_text()
    line = next(line for line in text.splitlines() if line.startswith("failregex = "))
    pattern = line.removeprefix("failregex = ")
    pattern = pattern.replace(
        "{{ " + variable + " | regex_escape }}", re.escape(hostname)
    )
    pattern = pattern.replace("<HOST>", r"(?P<host>\S+)")
    return re.compile(pattern)


def filter_regexes(
    path: pathlib.Path, variable: str, hostname: str
) -> list[re.Pattern]:
    # Every failregex pattern, including the indented continuation lines that
    # fail2ban reads as further patterns.
    patterns: list[str] = []
    reading = False
    for line in path.read_text().splitlines():
        if line.startswith("failregex = "):
            reading = True
            patterns.append(line.removeprefix("failregex = "))
        elif reading and line[:1].isspace() and line.strip():
            patterns.append(line.strip())
        else:
            reading = False
    escaped = "{{ " + variable + " | regex_escape }}"
    return [
        re.compile(
            pattern.replace(escaped, re.escape(hostname)).replace(
                "<HOST>", r"(?P<host>\S+)"
            )
        )
        for pattern in patterns
    ]


def access_line(vhost: str, request: str, status: int, path: str | None = None) -> str:
    # A vhost_combined line as fail2ban sees it, with the timestamp removed. It
    # ends with %U, by default the request's path without its query string.
    if path is None:
        path = request.split()[1].partition("?")[0]
    return (
        f'{vhost}:443 203.0.113.7 - - [] "{request} HTTP/1.1" {status} 28 "-" '
        f'"curl" 512 "{path}"'
    )


def combined_line(request: str, status: int, path: str) -> str:
    # A combined line as fail2ban sees it, with the timestamp removed and %U,
    # the path Apache routes by, at the end.
    return (
        f'203.0.113.7 - - [] "{request} HTTP/1.1" {status} 28 "-" "curl" 512 "{path}"'
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

# Loopback plus home, the VPN, and the office, as zabbix-mcp.rewse.jp allows.
TRUSTED_SOURCES = {"127.0.0.1", "::1"}
for _value in NETWORKS.values():
    TRUSTED_SOURCES.update([_value] if isinstance(_value, str) else _value)


def render_vhost(role: pathlib.Path, name: str, **variables) -> str:
    environment = jinja2.Environment(
        loader=jinja2.FileSystemLoader(role / "templates"),
        undefined=jinja2.StrictUndefined,
    )
    environment.filters["comment"] = lambda text: f"#\n# {text}\n#"
    return environment.get_template(name).render(
        ansible_managed="Ansible managed", networks=NETWORKS, **variables
    )


def require_ip_blocks(text: str) -> dict[str, set[str]]:
    # Maps each <Location> or <LocationMatch> argument to its Require ip sources.
    blocks: dict[str, set[str]] = {}
    current = None
    for line in (line.strip() for line in text.splitlines()):
        opened = re.match(r'^<Location(?:Match)? "?([^">]+)"?>$', line)
        if opened:
            current = opened.group(1)
            blocks[current] = set()
        elif line.startswith("</Location"):
            current = None
        elif current is not None and line.startswith("Require ip "):
            blocks[current].update(line.split()[2:])
    return blocks


def vhost_deploy_task(role: pathlib.Path, hostname: str) -> dict:
    tasks = load_yaml(role / "tasks" / "apache.yml")
    return next(
        task["ansible.builtin.template"]
        for task in tasks
        if "ansible.builtin.template" in task
        and task["ansible.builtin.template"]["src"] == f"{hostname}.conf.j2"
    )


class CouchDBAdminPathTest(unittest.TestCase):
    # Obsidian LiveSync replicates through the database paths from anywhere.
    # The server-level paths, all of which begin with an underscore, administer
    # CouchDB and are needed only from home, the VPN, and the office.
    HOSTNAME = "couchdb.rewse.jp"

    def admin_pattern(self) -> re.Pattern:
        blocks = require_ip_blocks(render_vhost(COUCHDB, f"{self.HOSTNAME}.conf.j2"))
        self.assertEqual(len(blocks), 1)
        ((pattern, sources),) = blocks.items()
        self.assertEqual(sources, TRUSTED_SOURCES)
        return re.compile(pattern)

    def test_vhost_is_deployed_from_the_template(self):
        task = vhost_deploy_task(COUCHDB, self.HOSTNAME)
        self.assertEqual(
            task["dest"], f"/etc/apache2/sites-available/{self.HOSTNAME}.conf"
        )
        self.assertFalse((COUCHDB / "files" / f"{self.HOSTNAME}.conf").exists())

    def test_admin_paths_are_limited_to_trusted_networks(self):
        pattern = self.admin_pattern()
        for path in (
            "/_active_tasks",
            "/_all_dbs",
            "/_cluster_setup",
            "/_config",
            "/_dbs_info",
            "/_membership",
            "/_node/_local/_config",
            "/_replicate",
            "/_replicator/x",
            "/_scheduler/jobs",
            "/_users/org.couchdb.user:x",
            "/_utils/",
        ):
            with self.subTest(path=path):
                self.assertTrue(pattern.search(path))

    def test_database_and_session_paths_stay_open(self):
        # LiveSync signs in through /_session; database names cannot begin
        # with an underscore, so their paths never match.
        pattern = self.admin_pattern()
        for path in (
            "/",
            "/_session",
            "/obsidian",
            "/obsidian/_changes",
            "/obsidian/_local/checkpoint",
            "/obsidian/_bulk_docs",
        ):
            with self.subTest(path=path):
                self.assertFalse(pattern.search(path))


class LiteLLMNetworkTest(unittest.TestCase):
    # The master key reaches every model, so the gateway answers only home, the
    # VPN, and the office.
    HOSTNAME = "litellm.rewse.jp"

    def test_vhost_is_deployed_from_the_template(self):
        task = vhost_deploy_task(LITELLM, self.HOSTNAME)
        self.assertEqual(
            task["dest"], f"/etc/apache2/sites-available/{self.HOSTNAME}.conf"
        )
        self.assertFalse((LITELLM / "files" / f"{self.HOSTNAME}.conf").exists())

    def test_vhost_allows_only_trusted_networks(self):
        text = render_vhost(LITELLM, f"{self.HOSTNAME}.conf.j2")
        self.assertEqual(require_ip_blocks(text), {"/": TRUSTED_SOURCES})
        self.assertNotIn("Require all granted", text)


class NvrFail2banTest(unittest.TestCase):
    def test_fail2ban_component_is_imported(self):
        imports = {
            task["ansible.builtin.import_tasks"]: task["tags"]
            for task in load_yaml(NVR / "tasks" / "main.yml")
        }
        self.assertEqual(imports.get("fail2ban.yml"), ["nvr_fail2ban"])
        roles = [
            dep["role"] for dep in load_yaml(NVR / "meta" / "main.yml")["dependencies"]
        ]
        self.assertIn("fail2ban", roles)

    def test_jail_reads_the_apache_log(self):
        section = jail(NVR / "templates" / "fail2ban-jail.conf.j2", "nvr")
        self.assertEqual(section["enabled"], "true")
        self.assertEqual(section["backend"], "auto")
        self.assertEqual(section["filter"], "nvr")
        self.assertEqual(section["logpath"], "/var/log/apache2/other_vhosts_access.log")

    def test_filter_matches_failed_frigate_logins_only(self):
        hostname = load_yaml(NVR / "vars" / "main.yml")["nvr_hostname"]
        self.assertEqual(hostname, "nvr.rewse.jp")
        regex = filter_regex(
            NVR / "templates" / "fail2ban-filter.conf.j2", "nvr_hostname", hostname
        )
        failed = access_line("nvr.rewse.jp", "POST /api/login", 401)
        match = regex.search(failed)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match["host"], "203.0.113.7")
        for line in (
            # A successful login.
            access_line("nvr.rewse.jp", "POST /api/login", 200),
            # A failed login on another virtual host.
            access_line("nas.rewse.jp", "POST /api/login", 401),
            # An expired session polling the API.
            access_line("nvr.rewse.jp", "GET /api/profile", 401),
        ):
            with self.subTest(line=line):
                self.assertIsNone(regex.search(line))


class NvrProxyHeaderTest(unittest.TestCase):
    TEXT = (NVR / "files" / "nvr.rewse.jp.conf").read_text()

    def lines(self, prefix: str) -> list[str]:
        return [
            line.strip()
            for line in self.TEXT.splitlines()
            if line.strip().startswith(prefix)
        ]

    def test_vhost_drops_client_proxy_auth_headers(self):
        # Frigate's nginx trusts these on its unauthenticated login and logout
        # locations and reflects X-Ingress-Path into the page, so only Apache
        # may decide what reaches it. The unset runs in fixups, before mod_proxy
        # builds the backend request.
        unset = self.lines("RequestHeader unset ")
        for header in (
            "Remote-Email",
            "Remote-Groups",
            "Remote-Name",
            "Remote-Role",
            "Remote-User",
            "X-Forwarded-User",
            "X-Ingress-Path",
            "X-Proxy-Secret",
        ):
            with self.subTest(header=header):
                self.assertIn(f"RequestHeader unset {header}", unset)

    def test_vhost_hides_the_backend_cache_status(self):
        self.assertIn("Header unset X-Cache-Status", self.lines("Header "))

    def test_vhost_sets_framing_and_transport_headers(self):
        for directive in (
            "Header always set Content-Security-Policy \"frame-ancestors 'self'\"",
            'Header always set Cross-Origin-Opener-Policy "same-origin"',
            'Header always set Strict-Transport-Security "max-age=31536000"',
            'Header always set X-Content-Type-Options "nosniff"',
            'Header always set X-Frame-Options "SAMEORIGIN"',
        ):
            with self.subTest(directive=directive):
                self.assertIn(directive, self.lines("Header "))

    def test_session_cookie_gains_secure_once(self):
        # The backend's Set-Cookie lives in the onsuccess table, which an
        # always edit would not see.
        edits = self.lines("Header edit Set-Cookie ")
        self.assertEqual(len(edits), 1)
        pattern, replacement = re.findall(r'"([^"]*)"', edits[0])
        replacement = replacement.replace("$1", r"\1")
        for cookie, expected in (
            (
                "frigate_token=abc; HttpOnly; Path=/",
                "frigate_token=abc; HttpOnly; Path=/; Secure",
            ),
            (
                "frigate_token=abc; Secure; HttpOnly; Path=/",
                "frigate_token=abc; Secure; HttpOnly; Path=/",
            ),
            (
                "frigate_token=abc; HttpOnly; Path=/; secure",
                "frigate_token=abc; HttpOnly; Path=/; secure",
            ),
            ("other=1; Path=/", "other=1; Path=/"),
        ):
            with self.subTest(cookie=cookie):
                self.assertEqual(re.sub(pattern, replacement, cookie), expected)
        self.assertNotRegex(self.TEXT, r"(?m)^\s*Header always edit\*? Set-Cookie")


class ZabbixPublicVhostTest(unittest.TestCase):
    # zabbix.rewse.jp opens the frontend and the API to the internet; the
    # default virtual host keeps /zabbix limited to trusted networks.
    HOSTNAME = "zabbix.rewse.jp"
    # Request lines that Apache routes to the login form, logged with the %U
    # it routes them by.
    LOGIN_SPELLINGS = (
        ("POST /zabbix/index.php", "/zabbix/index.php"),
        ("POST /zabbix/index.php?request=x", "/zabbix/index.php"),
        ("POST //zabbix//index.php", "/zabbix/index.php"),
        ("POST /zabbix/./index.php", "/zabbix/index.php"),
        ("POST /zabbix/%69ndex.php", "/zabbix/index.php"),
        ("POST /%7Aabbix/index%5Fmfa.php", "/zabbix/index_mfa.php"),
        ("POST /zabbix/index_mfa.php", "/zabbix/index_mfa.php"),
    )

    def test_vhost_is_deployed_from_the_template(self):
        task = vhost_deploy_task(ZABBIX_SERVER, self.HOSTNAME)
        self.assertEqual(
            task["dest"],
            "/etc/apache2/sites-available/{{ zabbix_server_hostname }}.conf",
        )
        imports = {
            task["ansible.builtin.import_tasks"]: task["tags"]
            for task in load_yaml(ZABBIX_SERVER / "tasks" / "main.yml")
        }
        self.assertEqual(imports.get("apache.yml"), ["zabbix_server_apache"])
        hostname = load_yaml(ZABBIX_SERVER / "vars" / "main.yml")[
            "zabbix_server_hostname"
        ]
        self.assertEqual(hostname, self.HOSTNAME)

    def test_vhost_opens_zabbix_to_everyone(self):
        text = render_vhost(
            ZABBIX_SERVER,
            f"{self.HOSTNAME}.conf.j2",
            zabbix_server_hostname=self.HOSTNAME,
        )
        self.assertIn(f"ServerName {self.HOSTNAME}", text)
        self.assertIn("RedirectMatch ^/$ /zabbix/", text)
        block = re.search(r'(?ms)^\s*<Location "/zabbix">\n(.*?)^\s*</Location>', text)
        self.assertIsNotNone(block)
        assert block is not None
        self.assertIn("Require all granted", block.group(1))
        self.assertEqual(require_ip_blocks(text), {"/zabbix": set()})

    def test_filter_matches_failed_logins_on_both_vhosts(self):
        regexes = filter_regexes(
            ZABBIX_SERVER / "templates" / "fail2ban-filter.conf.j2",
            "zabbix_server_hostname",
            self.HOSTNAME,
        )
        lines = []
        for request, path in self.LOGIN_SPELLINGS:
            # A wrong password or verification code re-renders the form, on
            # the public virtual host and on the default one.
            lines.append(access_line(self.HOSTNAME, request, 200, path))
            lines.append(combined_line(request, 200, path))
        for line in lines:
            with self.subTest(line=line):
                matches = [m for m in (r.search(line) for r in regexes) if m]
                self.assertTrue(matches)
                self.assertEqual(matches[0]["host"], "203.0.113.7")
        for line in (
            # A successful login redirects.
            access_line(self.HOSTNAME, "POST /zabbix/index.php", 302),
            access_line(
                self.HOSTNAME, "POST //zabbix/index.php", 302, "/zabbix/index.php"
            ),
            combined_line("POST /zabbix/index.php", 302, "/zabbix/index.php"),
            # Loading the login form.
            access_line(self.HOSTNAME, "GET /zabbix/index.php", 200),
            combined_line("GET /zabbix/index.php", 200, "/zabbix/index.php"),
            # The API answers every call with 200, failed or not.
            access_line(self.HOSTNAME, "POST /zabbix/api_jsonrpc.php", 200),
            access_line(
                self.HOSTNAME,
                "POST /zabbix/api_jsonrpc.php?/zabbix/index.php",
                200,
            ),
            combined_line(
                "POST /zabbix/index.php/../api_jsonrpc.php",
                200,
                "/zabbix/api_jsonrpc.php",
            ),
            # Another virtual host.
            access_line("nas.rewse.jp", "POST /zabbix/index.php", 200),
        ):
            with self.subTest(line=line):
                self.assertFalse([r for r in regexes if r.search(line)])

    def test_jail_reads_both_logs(self):
        section = jail(
            ZABBIX_SERVER / "templates" / "fail2ban-jail.conf.j2", "zabbix-web"
        )
        self.assertEqual(
            section["logpath"].split(),
            [
                "/var/log/apache2/access.log",
                "/var/log/apache2/other_vhosts_access.log",
            ],
        )


class ZabbixLoginMethodTest(unittest.TestCase):
    # Zabbix reads the login fields from $_REQUEST, so a query string logs in
    # as well as a form post, while the zabbix-web filter counts only POST.
    # Both the default virtual host and zabbix.rewse.jp refuse other methods
    # on the login pages when the query string names a login field.
    HOSTNAME = "zabbix.rewse.jp"
    TEMPLATES = ("zabbix-api.conf.j2", f"{HOSTNAME}.conf.j2")
    # Requests that keep working: the login form, the redirects and links
    # Zabbix itself builds, the Duo callback, and pages other than the login.
    ALLOWED = (
        ("GET", "/zabbix/"),
        ("GET", "/zabbix/index.php"),
        ("GET", "/zabbix/index.php?form=default"),
        ("GET", "/zabbix/index.php?reconnect=1"),
        ("GET", "/zabbix/index.php?request=zabbix.php%3Faction%3Ddashboard.view"),
        ("GET", "/zabbix/index_mfa.php?request=zabbix.php"),
        ("GET", "/zabbix/index_mfa.php?duo_code=abc&state=def"),
        ("GET", "/zabbix/zabbix.php?action=host.view&filter_name=center"),
        ("GET", "/zabbix/zabbix.php?enter=1&password=x"),
    )
    # Spellings Apache maps to a login page, with a query string that PHP
    # reads as a login field.
    REFUSED = (
        ("GET", "/zabbix?enter=1&name=Admin&password=x"),
        ("GET", "/zabbix/?enter=1&name=Admin&password=x"),
        ("GET", "/zabbix/index.php?enter=1&name=Admin&password=x"),
        ("GET", "/zabbix/index.php?name=Admin&password=x"),
        ("GET", "/zabbix/index_mfa.php?enter=1&verification_code=123456"),
        ("GET", "//zabbix//index.php?enter=1"),
        ("GET", "/zabbix/./index.php?enter=1"),
        ("GET", "/%7Aabbix/index%2Ephp?enter=1"),
        ("GET", "/zabbix/index.php/x?enter=1"),
        ("GET", "/zabbix/index.php?%65nter=1"),
        ("GET", "/zabbix/index.php?%65nter=1&x=%zz"),
        ("GET", "/zabbix/index.php?%65nter=1&x=%00"),
        ("GET", "/zabbix/index.php?x=1&+enter=1"),
        ("GET", "/zabbix/index.php?enter%5B%5D=1"),
        ("GET", "/zabbix/index.php?enter[]=1"),
        ("GET", "/zabbix/index.php?p%61ssword=x"),
        ("HEAD", "/zabbix/index.php?enter=1"),
        ("PUT", "/zabbix/index.php?enter=1"),
    )

    def rendered(self, name: str) -> str:
        return render_vhost(ZABBIX_SERVER, name, zabbix_server_hostname=self.HOSTNAME)

    def test_both_scopes_carry_the_same_rule_inside_the_zabbix_location(self):
        rules = []
        for name in self.TEMPLATES:
            with self.subTest(template=name):
                block = re.search(
                    r'(?ms)^\s*<Location "/zabbix">\n(.*?)^\s*</Location>',
                    self.rendered(name),
                )
                self.assertIsNotNone(block)
                assert block is not None
                rule = re.search(
                    r'(?ms)^\s*<If "([^"]+)">\n\s*Require all denied\n\s*</If>',
                    block.group(1),
                )
                self.assertIsNotNone(rule)
                assert rule is not None
                self.assertIn("%{REQUEST_METHOD} != 'POST'", rule.group(1))
                rules.append(rule.group(1))
        self.assertEqual(len(set(rules)), 1)

    @unittest.skipUnless(
        shutil.which("httpd") or shutil.which("apache2"), "no Apache to test with"
    )
    def test_apache_refuses_credentials_outside_post(self):
        module_dir = next(
            (d for d in APACHE_MODULE_DIRS if (d / "mod_authz_core.so").exists()),
            None,
        )
        if module_dir is None:
            self.skipTest("no Apache modules found")
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            ui = root / "ui"
            ui.mkdir()
            for page in ("index.php", "index_mfa.php", "zabbix.php"):
                (ui / page).write_text("ok\n")
            vhost = "\n".join(
                line.replace("*:443", f"127.0.0.1:{port}")
                for line in self.rendered(self.TEMPLATES[1]).splitlines()
                if not line.strip().startswith(("SSL", "Include "))
            )
            (root / "api.conf").write_text(self.rendered(self.TEMPLATES[0]))
            (root / "vhost.conf").write_text(vhost)
            modules = [
                f"LoadModule {name}_module {module_dir}/mod_{name}.so"
                for name in (
                    "mpm_prefork",
                    "authz_core",
                    "authz_host",
                    "alias",
                    "dir",
                    "unixd",
                )
                if (module_dir / f"mod_{name}.so").exists()
            ]
            config = root / "httpd.conf"
            config.write_text(
                "\n".join(
                    [
                        *modules,
                        f"Listen 127.0.0.1:{port}",
                        f"PidFile {root}/httpd.pid",
                        f"ErrorLog {root}/error.log",
                        "ServerName localhost",
                        f"DocumentRoot {root}",
                        "DirectoryIndex index.php",
                        f"Alias /zabbix {ui}",
                        f'<Directory "{ui}">',
                        "    Require all granted",
                        "</Directory>",
                        # The default virtual host, which rewse.jp reaches.
                        f"<VirtualHost 127.0.0.1:{port}>",
                        "    ServerName rewse.jp",
                        "</VirtualHost>",
                        f"Include {root}/api.conf",
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
                self.wait_for(port, server)
                for host in ("rewse.jp", self.HOSTNAME):
                    for method, target in self.ALLOWED:
                        with self.subTest(host=host, method=method, target=target):
                            self.assertNotEqual(
                                self.status(port, host, method, target), 403
                            )
                    for method, target in self.REFUSED:
                        with self.subTest(host=host, method=method, target=target):
                            self.assertEqual(
                                self.status(port, host, method, target), 403
                            )
                    # The form post itself reaches the page; the static file
                    # handler answers it with 405 instead of PHP's 200.
                    self.assertNotEqual(
                        self.status(
                            port, host, "POST", "/zabbix/index.php?enter=1", b"x=1"
                        ),
                        403,
                    )
            finally:
                server.terminate()
                server.wait(timeout=10)

    @staticmethod
    def wait_for(port: int, server: subprocess.Popen) -> None:
        for _ in range(100):
            if server.poll() is not None:
                raise AssertionError(server.stderr.read() if server.stderr else "")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    return
            except OSError:
                time.sleep(0.05)
        raise AssertionError("Apache did not start")

    @staticmethod
    def status(
        port: int, host: str, method: str, target: str, body: bytes | None = None
    ) -> int:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            connection.request(method, target, body=body, headers={"Host": host})
            return connection.getresponse().status
        finally:
            connection.close()


class StandbyHomeAssistantFail2banTest(unittest.TestCase):
    LOG = "/srv/homeassistant/config/home-assistant.log"

    def test_jail_is_always_enabled(self):
        # The standby serves hass.rewse.jp during a failover, and the jail has to
        # be running by then; a run cannot be counted on to happen in between.
        section = jail(
            HOMEASSISTANT / "templates" / "fail2ban-jail.conf.j2", "homeassistant"
        )
        self.assertEqual(section["enabled"], "true")
        self.assertEqual(section["logpath"], self.LOG)
        text = (SECONDARY / "tasks" / "fail2ban.yml").read_text()
        self.assertNotIn("homeassistant_fail2ban_enabled", text)
        self.assertNotIn("ansible.builtin.stat", text)

    def test_standby_creates_the_log_the_jail_reads(self):
        # homeassistant-sync excludes *.log*, so the log exists only if the
        # standby makes it, and rsync --delete leaves excluded files alone.
        self.assertIn(
            "--exclude='*.log*'",
            (SECONDARY / "templates" / "homeassistant-sync.j2").read_text(),
        )
        tasks = load_yaml(SECONDARY / "tasks" / "fail2ban.yml")
        touch = next(
            t["ansible.builtin.file"]
            for t in tasks
            if t.get("ansible.builtin.file", {}).get("path") == self.LOG
        )
        self.assertEqual(touch["state"], "touch")
        self.assertEqual(touch["access_time"], "preserve")
        self.assertEqual(touch["modification_time"], "preserve")


class HomeAssistantNameSwitchTest(unittest.TestCase):
    def test_name_switch_moves_only_the_https_forward(self):
        # CloudFront fronts the services and WAN port 80 is closed, so the failover
        # moves only the 443 forward.
        text = (SECONDARY / "templates" / "homeassistant-name-switch.j2").read_text()
        self.assertIn("FORWARDED_PORTS=(443)", text)
        self.assertNotIn("forward of 80", text)
        self.assertNotIn("FORWARDED_PORTS=(443 80)", text)

    def test_name_switch_reads_every_dns_policy(self):
        # The integration API pages its lists, and the console holds more DNS
        # policies than one default page, so the CNAME can sit past the first.
        text = (SECONDARY / "templates" / "homeassistant-name-switch.j2").read_text()
        self.assertIn("/dns/policies?limit=${PAGE_LIMIT}", text)
        self.assertRegex(text, r"(?m)^readonly PAGE_LIMIT=200$")
        self.assertIn("totalCount", text)


class FileBrowserForwardedForTest(unittest.TestCase):
    def test_vhost_drops_client_forwarded_for(self):
        # FileBrowser trusts X-Forwarded-For for its lockout and audit log, and
        # mod_proxy appends to a header the client sent rather than replacing it.
        # The unset runs in fixups, after mod_remoteip restores the client
        # address; an early unset races mod_remoteip in post_read_request.
        text = (FILEBROWSER / "templates" / "nas.rewse.jp.conf.j2").read_text()
        self.assertRegex(text, r"(?m)^\s*RequestHeader unset X-Forwarded-For$")
        self.assertNotRegex(text, r"(?m)^\s*RequestHeader unset X-Forwarded-For early")

    def test_vhost_drops_client_forwarded_host(self):
        # FileBrowser builds the session cookie domain and the WebAuthn origin
        # from the first X-Forwarded-Host value, and mod_proxy appends the real
        # host to a value the client sent.
        text = (FILEBROWSER / "templates" / "nas.rewse.jp.conf.j2").read_text()
        self.assertRegex(text, r"(?m)^\s*RequestHeader unset X-Forwarded-Host$")
        self.assertNotRegex(text, r"(?m)^\s*RequestHeader unset X-Forwarded-Host early")

    def test_vhost_drops_client_real_ip(self):
        # FileBrowser falls back to X-Real-IP for the client address when
        # X-Forwarded-For is empty, and mod_proxy passes it through untouched.
        text = (FILEBROWSER / "templates" / "nas.rewse.jp.conf.j2").read_text()
        self.assertRegex(text, r"(?m)^\s*RequestHeader unset X-Real-IP$")


def directive_lines(text: str, prefix: str) -> list[str]:
    return [
        line.strip() for line in text.splitlines() if line.strip().startswith(prefix)
    ]


def quoted_arguments(line: str) -> list[str]:
    return re.findall(r'"([^"]*)"', line)


class FileBrowserBrowserPolicyTest(unittest.TestCase):
    APP_POLICY = (
        "script-src 'self' 'nonce-abc123' https://cdn.jsdelivr.net"
        " https://www.google.com https://www.gstatic.com"
    )

    @classmethod
    def setUpClass(cls):
        cls.text = render_vhost(
            FILEBROWSER,
            "nas.rewse.jp.conf.j2",
            filebrowser_hostname="nas.rewse.jp",
            filebrowser_port=8080,
        )

    def test_app_policy_loses_third_party_script_sources(self):
        # The app's own policy arrives with the proxied response, which lives in
        # the onsuccess table, so the edit must not use always.
        edits = directive_lines(self.text, "Header edit* Content-Security-Policy ")
        self.assertEqual(len(edits), 1)
        pattern, replacement = quoted_arguments(edits[0])
        self.assertEqual(replacement, "")
        edited = re.sub(pattern, replacement, self.APP_POLICY)
        self.assertEqual(edited, "script-src 'self' 'nonce-abc123'")
        self.assertNotRegex(
            self.text, r"(?m)^\s*Header always edit\*? Content-Security"
        )

    def test_edit_keeps_other_hosts_that_share_a_prefix(self):
        edits = directive_lines(self.text, "Header edit* Content-Security-Policy ")
        pattern, replacement = quoted_arguments(edits[0])
        policy = "script-src 'self' https://www.google.com.example"
        self.assertEqual(re.sub(pattern, replacement, policy), policy)

    def test_second_policy_covers_everything_but_scripts(self):
        # A second policy is enforced alongside the app's. It sets no
        # default-src or script-src, which would block the app's nonce scripts.
        lines = directive_lines(self.text, "Header always set Content-Security-Policy ")
        self.assertEqual(len(lines), 1)
        (policy,) = quoted_arguments(lines[0])
        directives = {
            part.split()[0]: part.split()[1:]
            for part in (piece.strip() for piece in policy.split(";"))
            if part
        }
        self.assertEqual(
            directives,
            {
                "base-uri": ["'self'"],
                "font-src": ["'self'", "data:"],
                "form-action": ["'self'"],
                "frame-ancestors": ["'self'"],
                "img-src": ["'self'", "data:", "blob:"],
                "media-src": ["'self'", "blob:"],
                "object-src": ["'none'"],
                "style-src": ["'self'", "'unsafe-inline'"],
            },
        )

    def test_vhost_sets_framing_and_transport_headers(self):
        for directive in (
            'Header always set Cross-Origin-Opener-Policy "same-origin"',
            'Header always set Strict-Transport-Security "max-age=31536000"',
            'Header always set X-Content-Type-Options "nosniff"',
            'Header always set X-Frame-Options "SAMEORIGIN"',
        ):
            with self.subTest(directive=directive):
                self.assertIn(directive, directive_lines(self.text, "Header "))

    def test_cross_site_api_writes_are_rejected_before_the_proxy(self):
        block = re.search(
            r"(?ms)^\s*RewriteCond %\{REQUEST_METHOD\} (\S+)\n"
            r"\s*RewriteCond %\{HTTP:Sec-Fetch-Site\} =cross-site\n"
            r"\s*RewriteRule (\S+) - \[F\]$",
            self.text,
        )
        self.assertIsNotNone(block)
        assert block is not None
        method, path = re.compile(block[1].lstrip("!")), re.compile(block[2])
        self.assertTrue(block[1].startswith("!"))
        for allowed in ("GET", "HEAD", "OPTIONS"):
            self.assertIsNotNone(method.search(allowed))
        for rejected in ("DELETE", "PATCH", "POST", "PUT"):
            self.assertIsNone(method.search(rejected))
        self.assertIsNotNone(path.search("/api/resources"))
        self.assertIsNone(path.search("/files/api/"))
        self.assertLess(block.start(), self.text.index("[P,L]"))

    def auth_rule(self) -> tuple[re.Pattern, re.Pattern]:
        block = re.search(
            r"(?ms)^\s*RewriteCond %\{THE_REQUEST\} (\S+)\n"
            r"\s*RewriteRule (\S+) - \[F\]$",
            self.text,
        )
        self.assertIsNotNone(block)
        assert block is not None
        self.assertLess(block.start(), self.text.index("[P,L]"))
        return re.compile(block[1]), re.compile(block[2])

    def test_login_is_reached_only_in_its_canonical_spelling(self):
        # The fail2ban filter matches the request line as logged, so a login
        # spelled another way that Apache still maps to /api/auth/login would
        # be counted by nothing. Apache normalizes the URI the rule sees, so
        # every case below arrives at the rule as /api/auth/login.
        request, uri = self.auth_rule()
        self.assertIsNotNone(uri.search("/api/auth/login"))
        for target in ("/api/auth/login", "/api/auth/login?x=%20"):
            with self.subTest(target=target):
                self.assertIsNone(request.search(f"POST {target} HTTP/1.1"))
        for target in (
            "//api/auth/login",
            "/api//auth/login",
            "/api/auth/./login",
            "/api/x/../auth/login",
            "/api/auth/%6cogin",
        ):
            with self.subTest(target=target):
                self.assertIsNotNone(request.search(f"POST {target} HTTP/1.1"))

    def test_rewrite_engine_is_on_before_the_rules(self):
        engine = self.text.index("RewriteEngine on")
        self.assertLess(engine, self.text.index("RewriteCond"))


class GrafanaCookieTest(unittest.TestCase):
    def test_session_cookie_is_sent_over_https_only(self):
        # Sessions last ten years, and a cookie without Secure also goes out
        # with any plain http:// request to the name, before a redirect.
        text = (TESLAMATE / "templates" / "grafana.env.j2").read_text()
        self.assertRegex(text, r"(?m)^GF_SECURITY_COOKIE_SECURE=true$")


def flatten_tasks(tasks: list[dict], inherited: dict | None = None) -> list[dict]:
    # Blocks pass their keywords down, so each task carries what it runs with.
    inherited = inherited or {}
    flat = []
    for task in tasks:
        merged = {**inherited, **task}
        if "block" in task:
            keywords = {k: v for k, v in task.items() if k not in ("block", "name")}
            flat.extend(flatten_tasks(task["block"], {**inherited, **keywords}))
        else:
            flat.append(merged)
    return flat


def conditions(task: dict) -> list[str]:
    when = task.get("when", [])
    return [when] if isinstance(when, str) else list(when)


class UdmCloudfrontTest(unittest.TestCase):
    TASKS = UDM / "tasks" / "cloudfront.yml"

    def tasks(self) -> list[dict]:
        return flatten_tasks(load_yaml(self.TASKS))

    def test_udm_cloudfront_tasks_never_touch_ssh_forwards(self):
        # The SSH forwards are how the hosts are reached when the web path
        # breaks, so the component selects the web forwards by port and never
        # names the SSH ports at all.
        for path in (
            self.TASKS,
            UDM / "defaults" / "main.yml",
            UDM / "vars" / "main.yml",
        ):
            text = path.read_text()
            for port in ("11022", "21022"):
                self.assertNotIn(port, text, path)
        text = self.TASKS.read_text()
        for port in ("443", "80"):
            self.assertIn(f"selectattr('dst_port', 'equalto', '{port}')", text)

    def test_https_check_accounts_for_every_web_forward(self):
        # A forward that reaches a web port by a range, a list, or another WAN
        # port bypasses the CloudFront limit, so the check before any change
        # sees every forward the filter selects, not only exact port matches.
        tasks = self.tasks()
        selection = next(
            t
            for t in tasks
            if "__udm_cloudfront_https_forwards"
            in t.get("ansible.builtin.set_fact", {})
        )
        text = str(selection)
        reads = re.findall(r"__udm_cloudfront_forwards\.json\.data[^}]*", text)
        self.assertTrue(reads)
        for read in reads:
            self.assertRegex(
                read,
                r"^__udm_cloudfront_forwards\.json\.data\s*\|\s*udm_web_forwards\b",
            )
        check = next(
            t
            for t in tasks
            if "__udm_cloudfront_https_forwards | length == 1"
            in t.get("ansible.builtin.assert", {}).get("that", [])
        )
        self.assertIn("__udm_cloudfront_web_forwards", str(check))
        self.assertIn("__udm_cloudfront_http_forwards", str(check))
        first_write = next(
            i
            for i, t in enumerate(tasks)
            if t.get("ansible.builtin.uri", {}).get("method") in ("DELETE", "PUT")
            and "traffic-matching-lists" not in t["ansible.builtin.uri"]["url"]
        )
        self.assertLess(tasks.index(check), first_write)

    def test_component_is_imported_and_off_by_default(self):
        imports = {
            task["ansible.builtin.import_tasks"]: task.get("tags")
            for task in load_yaml(UDM / "tasks" / "main.yml")
        }
        self.assertEqual(imports.get("cloudfront.yml"), ["udm_cloudfront", "update"])
        defaults = load_yaml(UDM / "defaults" / "main.yml")
        self.assertIs(defaults["udm_cloudfront_enforce"], False)

    def test_api_key_is_the_failover_secret_reference(self):
        ours = load_yaml(UDM / "vars" / "main.yml")
        theirs = load_yaml(SECONDARY / "vars" / "main.yml")
        self.assertEqual(
            ours["udm_unifi_api_key"],
            theirs["homeassistant_ha_secondary_unifi_api_key"],
        )
        self.assertEqual(
            ours["udm_unifi_console"],
            theirs["homeassistant_ha_secondary_unifi_console"],
        )

    def test_tasks_run_on_the_controller_without_become(self):
        for task in self.tasks():
            self.assertEqual(task.get("delegate_to"), "localhost", task["name"])
            self.assertIs(task.get("become"), False, task["name"])

    def test_reads_run_in_check_mode_and_writes_do_not(self):
        calls = [task for task in self.tasks() if "ansible.builtin.uri" in task]
        self.assertTrue(calls)
        for task in calls:
            method = task["ansible.builtin.uri"].get("method", "GET")
            if method == "GET":
                self.assertIs(task.get("check_mode"), False, task["name"])
            else:
                self.assertIn("not ansible_check_mode", conditions(task), task["name"])

    def test_only_the_address_group_changes_without_enforce(self):
        reads = ("ansible.builtin.assert", "ansible.builtin.set_fact")
        for task in self.tasks():
            uri = task.get("ansible.builtin.uri")
            if any(name in task for name in reads) or (
                uri is not None and uri.get("method", "GET") == "GET"
            ):
                continue
            if uri is not None and "traffic-matching-lists" in uri["url"]:
                self.assertNotIn("udm_cloudfront_enforce", conditions(task))
            else:
                self.assertIn("udm_cloudfront_enforce", conditions(task), task["name"])

    def test_originals_are_saved_before_anything_is_removed(self):
        names = [task["name"] for task in self.tasks()]
        backup = next(i for i, n in enumerate(names) if "Save" in n)
        for i, task in enumerate(self.tasks()):
            module = task.get("ansible.builtin.uri", {})
            if module.get("method") in ("DELETE", "PUT") and (
                "traffic-matching-lists" not in str(module.get("url", ""))
            ):
                self.assertGreater(i, backup, task["name"])


class UdmCloudfrontWriteTest(unittest.TestCase):
    TASKS = UDM / "tasks" / "cloudfront.yml"

    def tasks(self) -> list[dict]:
        return flatten_tasks(load_yaml(self.TASKS))

    def index(self, predicate) -> int:
        return next(i for i, task in enumerate(self.tasks()) if predicate(task))

    def test_failed_writes_report_status_and_body(self):
        # The request carries the API key, so it stays no_log; a separate
        # check prints only the status and the response body.
        tasks = self.tasks()
        for i, task in enumerate(tasks):
            uri = task.get("ansible.builtin.uri")
            if uri is None or uri.get("method", "GET") == "GET":
                continue
            with self.subTest(task=task["name"]):
                self.assertIs(task.get("no_log"), True)
                self.assertEqual(str(task.get("failed_when")), "False")
                self.assertIs(uri.get("return_content"), True)
                register = task["register"]
                check = next(
                    later
                    for later in tasks[i + 1 :]
                    if "ansible.builtin.assert" in later
                    and register in str(later["ansible.builtin.assert"]["that"])
                )
                message = check["ansible.builtin.assert"]["fail_msg"]
                self.assertIn("status", message)
                self.assertIn("json", message)
                self.assertNotIn("loop", check)
                self.assertNotIn("headers", message)
                self.assertNotIn("invocation", message)

    def test_https_limit_is_read_back(self):
        put = self.index(
            lambda t: (
                t.get("ansible.builtin.uri", {}).get("method") == "PUT"
                and "portforward" in t["ansible.builtin.uri"]["url"]
            )
        )
        tasks = self.tasks()
        reread = next(
            i
            for i, t in enumerate(tasks)
            if i > put
            and "ansible.builtin.uri" in t
            and t["ansible.builtin.uri"].get("method", "GET") == "GET"
            and "portforward" in t["ansible.builtin.uri"]["url"]
        )
        check = next(
            t
            for t in tasks[reread + 1 :]
            if "ansible.builtin.assert" in t and tasks[reread]["register"] in str(t)
        )
        that = str(check["ansible.builtin.assert"]["that"])
        for field in (
            "src_firewall_group_id",
            "src_limiting_enabled",
            "src_limiting_type",
        ):
            self.assertIn(field, that)

    def test_no_ipv6_web_allow_may_remain(self):
        tasks = self.tasks()
        text = self.TASKS.read_text()
        self.assertIn("udm_web_allows", text)
        self.assertIn("udm_web_only", text)
        deletes = [
            i
            for i, t in enumerate(tasks)
            if t.get("ansible.builtin.uri", {}).get("method") == "DELETE"
        ]
        # Before any change: every web allow can be removed without closing
        # another port.
        precheck = self.index(
            lambda t: (
                "__udm_cloudfront_ipv6_web"
                in str(t.get("ansible.builtin.assert", {}).get("that", ""))
            )
        )
        first_write = min(
            i
            for i, t in enumerate(tasks)
            if t.get("ansible.builtin.uri", {}).get("method") in ("DELETE", "PUT")
            and "traffic-matching-lists" not in t["ansible.builtin.uri"]["url"]
        )
        self.assertLess(precheck, first_write)
        # After the deletes: the policies are read again and none remains.
        reread = next(
            i
            for i, t in enumerate(tasks)
            if i > max(deletes)
            and "ansible.builtin.uri" in t
            and t["ansible.builtin.uri"].get("method", "GET") == "GET"
            and "firewall/policies" in t["ansible.builtin.uri"]["url"]
        )
        self.assertTrue(
            any(
                "ansible.builtin.assert" in t and "udm_web_allows" in str(t)
                for t in tasks[reread + 1 :]
            )
        )

    def test_originals_are_kept_in_the_state_directory(self):
        self.assertNotIn("tempfile", self.TASKS.read_text())
        self.assertNotIn("/tmp", self.TASKS.read_text())
        variables = load_yaml(UDM / "vars" / "main.yml")
        self.assertRegex(
            variables["udm_cloudfront_backup_dir"], r"XDG_STATE_HOME.*/udm-cloudfront"
        )
        tasks = self.tasks()
        directory = next(
            t["ansible.builtin.file"]
            for t in tasks
            if t.get("ansible.builtin.file", {}).get("path")
            == "{{ udm_cloudfront_backup_dir }}"
        )
        self.assertEqual(directory["state"], "directory")
        self.assertEqual(directory["mode"], "0700")
        saved = next(
            t["ansible.builtin.copy"] for t in tasks if "ansible.builtin.copy" in t
        )
        self.assertTrue(saved["dest"].startswith("{{ udm_cloudfront_backup_dir }}/"))
        self.assertEqual(saved["mode"], "0600")
        agents = (REPO_ROOT / "AGENTS.md").read_text()
        self.assertIn("~/.local/state/udm-cloudfront/", agents)


def load_udm_firewall():
    path = UDM / "filter_plugins" / "udm_firewall.py"
    spec = importlib.util.spec_from_file_location("udm_firewall", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class UdmFirewallFilterTest(unittest.TestCase):
    EXTERNAL = "external-zone"
    LISTS: ClassVar[list[dict]] = [
        {
            "id": "https",
            "type": "PORTS",
            "items": [{"type": "PORT_NUMBER", "value": 443}],
        },
        {
            "id": "http",
            "type": "PORTS",
            "items": [{"type": "PORT_NUMBER", "value": 80}],
        },
        {
            "id": "ssh",
            "type": "PORTS",
            "items": [{"type": "PORT_NUMBER", "value": 11022}],
        },
    ]

    def setUp(self):
        self.module = load_udm_firewall()

    @classmethod
    def policy(cls, name: str, ports=None, **overrides) -> dict:
        policy = {
            "name": name,
            "enabled": True,
            "action": {"type": "ALLOW"},
            "source": {"zoneId": cls.EXTERNAL},
            "destination": {"zoneId": "internal-zone"},
            "ipProtocolScope": {
                "ipVersion": "IPV6",
                "protocolFilter": {
                    "type": "NAMED_PROTOCOL",
                    "protocol": {"name": "TCP"},
                    "matchOpposite": False,
                },
            },
            "metadata": {"origin": "USER_DEFINED"},
        }
        if isinstance(ports, str):
            policy["destination"]["trafficFilter"] = {
                "type": "IP_ADDRESS",
                "portFilter": {
                    "type": "TRAFFIC_MATCHING_LIST",
                    "matchOpposite": False,
                    "trafficMatchingListId": ports,
                },
            }
        elif ports is not None:
            policy["destination"]["trafficFilter"] = {
                "type": "PORT",
                "portFilter": {"type": "PORTS", "matchOpposite": False, "items": ports},
            }
        for key, value in overrides.items():
            policy[key] = value
        return policy

    @staticmethod
    def port(value: int) -> dict:
        return {"type": "PORT_NUMBER", "value": value}

    def names(self, policies: list[dict]) -> list[str]:
        return [policy["name"] for policy in policies]

    def test_selects_every_ipv6_capable_allow_that_reaches_a_web_port(self):
        tcp_udp = {
            "ipVersion": "IPV6",
            "protocolFilter": {"type": "PRESET", "preset": {"name": "TCP_UDP"}},
        }
        policies = [
            self.policy("https list", "https"),
            self.policy("http inline", [self.port(80)]),
            self.policy(
                "dual stack web",
                [self.port(80), self.port(443)],
                ipProtocolScope={"ipVersion": "IPV4_AND_IPV6"},
            ),
            self.policy("web and ssh", [self.port(443), self.port(11022)]),
            self.policy(
                "low range", [{"type": "PORT_NUMBER_RANGE", "start": 1, "stop": 1024}]
            ),
            self.policy(
                "all but ssh",
                None,
                destination={
                    "zoneId": "internal-zone",
                    "trafficFilter": {
                        "portFilter": {
                            "type": "PORTS",
                            "matchOpposite": True,
                            "items": [self.port(22)],
                        }
                    },
                },
            ),
            self.policy("tcp and udp", [self.port(443)], ipProtocolScope=tcp_udp),
            self.policy(
                "any protocol", [self.port(443)], ipProtocolScope={"ipVersion": "IPV6"}
            ),
            self.policy("unknown list", "missing"),
            self.policy("every port", None, ipProtocolScope={"ipVersion": "IPV6"}),
            # None of these reaches a web port over IPv6 with new TCP connections.
            self.policy("ssh", "ssh"),
            self.policy("ipv4 only", "https", ipProtocolScope={"ipVersion": "IPV4"}),
            self.policy("disabled", "https", enabled=False),
            self.policy("from internal", "https", source={"zoneId": "internal-zone"}),
            self.policy("block", "https", action={"type": "BLOCK"}),
            self.policy(
                "icmpv6",
                None,
                ipProtocolScope={
                    "ipVersion": "IPV6",
                    "protocolFilter": {
                        "type": "NAMED_PROTOCOL",
                        "protocol": {"name": "ICMPV6"},
                        "matchOpposite": False,
                    },
                },
            ),
            self.policy(
                "udp",
                [self.port(443)],
                ipProtocolScope={
                    "ipVersion": "IPV6",
                    "protocolFilter": {
                        "type": "NAMED_PROTOCOL",
                        "protocol": {"name": "UDP"},
                        "matchOpposite": False,
                    },
                },
            ),
            self.policy(
                "return traffic",
                None,
                ipProtocolScope={"ipVersion": "IPV4_AND_IPV6"},
                connectionStateFilter=["RELATED", "ESTABLISHED"],
                metadata={"origin": "SYSTEM_DEFINED"},
            ),
        ]

        web = self.module.udm_web_allows(policies, self.LISTS, self.EXTERNAL)

        self.assertEqual(
            self.names(web),
            [
                "https list",
                "http inline",
                "dual stack web",
                "web and ssh",
                "low range",
                "all but ssh",
                "tcp and udp",
                "any protocol",
                "unknown list",
                "every port",
            ],
        )
        self.assertEqual(
            self.names(self.module.udm_web_only(web, self.LISTS)),
            [
                "https list",
                "http inline",
                "dual stack web",
                "tcp and udp",
                "any protocol",
            ],
        )

    def test_web_only_leaves_other_origins(self):
        derived = self.policy("derived", "https", metadata={"origin": "DERIVED"})

        self.assertEqual(self.module.udm_web_only([derived], self.LISTS), [])

    def test_counts_an_unknown_preset_as_tcp(self):
        # A preset the filter does not know may include TCP.
        scope = {
            "ipVersion": "IPV6",
            "protocolFilter": {"type": "PRESET", "preset": {"name": "ALL_NEW"}},
        }
        policies = [self.policy("new preset", [self.port(443)], ipProtocolScope=scope)]

        web = self.module.udm_web_allows(policies, self.LISTS, self.EXTERNAL)

        self.assertEqual(self.names(web), ["new preset"])

    def test_unparsed_port_items_cover_the_web_ports(self):
        unknown = {"type": "PORT_GROUP", "value": "web"}
        opposite = {
            "unknown item": [self.port(443), unknown],
            "web ports and unknown item": [self.port(80), self.port(443), unknown],
            "open range": [self.port(443), {"type": "PORT_NUMBER_RANGE", "start": 1}],
            "text port": [self.port(80), {"type": "PORT_NUMBER", "value": "443"}],
        }
        named = {
            "text port": [{"type": "PORT_NUMBER", "value": "443"}],
            "open range": [{"type": "PORT_NUMBER_RANGE", "start": 1}],
        }
        cases = [
            (
                "opposite",
                name,
                self.policy(
                    name,
                    None,
                    destination={
                        "zoneId": "internal-zone",
                        "trafficFilter": {
                            "portFilter": {
                                "type": "PORTS",
                                "matchOpposite": True,
                                "items": items,
                            }
                        },
                    },
                ),
            )
            for name, items in opposite.items()
        ] + [("named", name, self.policy(name, items)) for name, items in named.items()]
        for kind, name, policy in cases:
            with self.subTest(kind=kind, policy=name):
                self.assertEqual(
                    self.module._admitted_web_ports(policy, self.LISTS), {80, 443}
                )
                web = self.module.udm_web_allows([policy], self.LISTS, self.EXTERNAL)
                self.assertEqual(self.names(web), [name])
                self.assertEqual(self.module.udm_web_only(web, self.LISTS), [])

    @staticmethod
    def forward(name: str, dst_port, fwd_port=None, **overrides) -> dict:
        forward = {
            "_id": f"id-{name}",
            "name": name,
            "enabled": True,
            "pfwd_interface": "wan",
            "dst_port": dst_port,
            "fwd": "192.0.2.10",
            "fwd_port": dst_port if fwd_port is None else fwd_port,
            "proto": "tcp_udp",
        }
        forward.update(overrides)
        return forward

    def test_selects_every_enabled_forward_that_reaches_a_web_port(self):
        unset_enabled = self.forward("enabled unset", "443")
        del unset_enabled["enabled"]
        unset_proto = self.forward("protocol unset", "80")
        del unset_proto["proto"]
        forwards = [
            self.forward("https", "443"),
            self.forward("http", "80", proto="tcp"),
            self.forward("alternate https", "8443", "443"),
            self.forward("http to https", "80", "443"),
            self.forward("low range", "1-1024"),
            self.forward("web list", "80,443"),
            self.forward("spaced list", "8080, 443"),
            self.forward("number", 443),
            self.forward("unparsed port", "443-"),
            self.forward("fwd port unset", "443", ""),
            self.forward("unknown protocol", "443", proto="sctp_tcp"),
            unset_enabled,
            unset_proto,
            # None of these reaches a web port over TCP.
            self.forward("ssh", "11022", "22", proto="tcp"),
            self.forward("ssh fwd port unset", "21022", ""),
            self.forward("quic", "443", proto="udp"),
            self.forward("disabled", "443", enabled=False),
            self.forward("high range", "8000-8100"),
            self.forward("high list", "8080,8443"),
        ]

        web = self.module.udm_web_forwards(forwards)

        self.assertEqual(
            self.names(web),
            [
                "https",
                "http",
                "alternate https",
                "http to https",
                "low range",
                "web list",
                "spaced list",
                "number",
                "unparsed port",
                "fwd port unset",
                "unknown protocol",
                "enabled unset",
                "protocol unset",
            ],
        )


class InternetTlsVerificationTest(unittest.TestCase):
    # The relay leg crosses the internet carrying credentials, so an unverified
    # peer lets an on-path attacker collect them.
    CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"

    def test_postfix_verifies_the_relay(self):
        lines = {
            task["ansible.builtin.lineinfile"]["line"]
            for task in load_yaml(POSTFIX_CLIENT / "tasks" / "main_cf.yml")
        }
        self.assertIn("smtp_tls_security_level = secure", lines)
        # Read before the smtp client enters its chroot, unlike smtp_tls_CApath.
        self.assertIn(f"smtp_tls_CAfile = {self.CA_BUNDLE}", lines)


class SecurityAgentPentestTest(unittest.TestCase):
    # AWS Security Agent pentests send a secret header so that fail2ban, which
    # would otherwise ban them from every service on the host within seconds,
    # ignores their address. Apache records which addresses sent it.
    LOG_LINE = (
        "CustomLog ${APACHE_LOG_DIR}/security_agent_pentest.log "
        "security_agent_pentest env=security_agent_pentest"
    )
    SCRIPT = HTTPD / "files" / "fail2ban-ignore-security-agent"

    def ignored(self, log: str | None, ip: str) -> bool:
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "pentest.log"
            if log is not None:
                path.write_text(log)
            result = subprocess.run(
                ["sh", str(self.SCRIPT), ip, str(path)], check=False
            )
        return result.returncode == 0

    def test_apache_marks_and_strips_the_header(self):
        text = (HTTPD / "templates" / "security-agent-pentest.conf.j2").read_text()
        header = "X-Continuum-Pentest"
        self.assertRegex(
            text,
            # The token is a regular expression here, so it is escaped to
            # be matched literally.
            rf'(?m)^SetEnvIf {header} "\^\{{\{{ '
            r"httpd_security_agent_pentest_token \| regex_escape \}\}\$\" "
            r"security_agent_pentest$",
        )
        # Not "early": that runs before SetEnvIf reads the header.
        self.assertRegex(text, rf"(?m)^RequestHeader unset {header}$")
        self.assertNotIn("X-Security-Agent-Pentest", text)
        self.assertIn(self.LOG_LINE, text.splitlines())

    def test_vhosts_with_their_own_logs_also_record_the_header(self):
        # A CustomLog in a vhost stops it inheriting the server's.
        for path in ROLES.glob("*/templates/*.rewse.jp.conf.j2"):
            text = path.read_text()
            if "CustomLog" in text:
                lines = [line.strip() for line in text.splitlines()]
                self.assertIn(self.LOG_LINE, lines, path)

    def test_token_is_a_secret_reference(self):
        variables = load_yaml(HTTPD / "vars" / "main.yml")
        self.assertRegex(
            variables["httpd_security_agent_pentest_token"],
            r"^\{\{ lookup\('pipe', 'op read op://ansible/\w+/password'\) \}\}$",
        )

    def test_every_jail_but_sshd_asks_the_script(self):
        text = (HTTPD / "templates" / "fail2ban-security-agent.conf.j2").read_text()
        self.assertRegex(
            text,
            r"(?m)^ignorecommand = /usr/local/sbin/fail2ban-ignore-security-agent "
            r"<ip> /var/log/apache2/security_agent_pentest\.log$",
        )
        self.assertEqual(
            jail(FAIL2BAN / "templates" / "sshd.conf.j2", "sshd")["ignorecommand"], ""
        )

    def test_script_ignores_an_address_seen_recently(self):
        now = int(time.time())
        self.assertTrue(self.ignored(f"{now - 60} 192.0.2.1\n", "192.0.2.1"))

    def test_script_bans_an_address_seen_long_ago(self):
        now = int(time.time())
        self.assertFalse(self.ignored(f"{now - 3 * 3600} 192.0.2.1\n", "192.0.2.1"))

    def test_script_bans_other_addresses(self):
        now = int(time.time())
        self.assertFalse(self.ignored(f"{now} 192.0.2.10\n", "192.0.2.1"))

    def test_script_bans_when_the_log_is_missing(self):
        self.assertFalse(self.ignored(None, "192.0.2.1"))


if __name__ == "__main__":
    unittest.main()
