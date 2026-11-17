#!/usr/bin/env python3
"""Regression tests for the fail2ban filters of the services on fox."""

import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

import jinja2
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROLES = REPO_ROOT / "roles"
# What fail2ban's <HOST> accepts, close enough for these filters.
HOST = r"(?P<host>[\w\-.:]+)"


def failregexes(path: pathlib.Path) -> list[re.Pattern]:
    """Return the failregex lines of a filter, compiled as fail2ban does."""
    patterns = []
    in_failregex = False
    for line in path.read_text().splitlines():
        if line.startswith("failregex = "):
            in_failregex = True
            line = line.removeprefix("failregex = ")
        elif in_failregex and line.startswith((" ", "\t")):
            line = line.strip()
        else:
            in_failregex = False
            continue
        patterns.append(re.compile(line.replace("<HOST>", HOST)))
    return patterns


def banned_host(path: pathlib.Path, line: str) -> str | None:
    # fail2ban searches the line with the timestamp cut out.
    for pattern in failregexes(path):
        match = pattern.search(line)
        if match:
            return match["host"]
    return None


def fail2ban_regex(path: pathlib.Path, log: str) -> str:
    """Run fail2ban-regex on a log and return the addresses it would ban."""
    binary = shutil.which("fail2ban-regex")
    assert binary is not None
    with tempfile.TemporaryDirectory() as tmp:
        log_path = pathlib.Path(tmp) / "test.log"
        log_path.write_text(log)
        result = subprocess.run(
            [binary, "--out", "ip", str(log_path), str(path)],
            capture_output=True,
            text=True,
            check=True,
        )
    return result.stdout


class HomeAssistantFilterTest(unittest.TestCase):
    FILTER = ROLES / "homeassistant" / "files" / "fail2ban-filter.conf"
    PREFIX = (
        " WARNING (MainThread) [homeassistant.components.http.ban] "
        "Login attempt or request with invalid authentication from"
    )

    def line(self, host: str, addr: str, url: str, user_agent: str) -> str:
        # The format of homeassistant.components.http.ban.process_wrong_login.
        return f"{self.PREFIX} {host} ({addr}). Requested URL: '{url}'. ({user_agent})"

    def test_bans_the_logged_client_address(self):
        for host, addr in (
            ("203.0.113.7", "203.0.113.7"),
            ("client.example.net", "203.0.113.7"),
            ("2001:db8::7", "2001:db8::7"),
        ):
            with self.subTest(addr=addr):
                line = self.line(host, addr, "/auth/token", "Mozilla/5.0")
                self.assertEqual(banned_host(self.FILTER, line), addr)

    def test_ignores_an_address_in_the_user_agent(self):
        forged = f"{self.PREFIX} 192.0.2.1 (192.0.2.1). Requested URL: '/'"
        line = self.line("203.0.113.7", "203.0.113.7", "/auth/token", forged)
        self.assertEqual(banned_host(self.FILTER, line), "203.0.113.7")

    def test_ignores_an_address_in_the_url(self):
        forged = f"/?{self.PREFIX} 192.0.2.1 (192.0.2.1). Requested URL: 'x"
        line = self.line("203.0.113.7", "203.0.113.7", forged, "Mozilla/5.0")
        self.assertEqual(banned_host(self.FILTER, line), "203.0.113.7")

    def test_bans_any_url_and_user_agent(self):
        for url, user_agent in (
            ("/", ""),
            ("/api/", "None"),
            ("/auth/token?x='y'", "Mozilla/5.0 (X11; Linux x86_64)"),
        ):
            with self.subTest(url=url, user_agent=user_agent):
                line = self.line("203.0.113.7", "203.0.113.7", url, user_agent)
                self.assertEqual(banned_host(self.FILTER, line), "203.0.113.7")

    def test_ignores_the_message_inside_another_entry(self):
        # Another logger that echoes text a client controls, such as an MQTT
        # payload, can carry a copy of the message after its own prefix.
        message = self.line("192.0.2.1", "192.0.2.1", "/", "curl").removeprefix(" ")
        for line in (
            f" ERROR (MainThread) [custom_components.x] {message}",
            f" WARNING (MainThread) [homeassistant.components.mqtt] Payload: {message}",
            f" WARNING (SyncWorker_0) [homeassistant.components.mqtt] {message}",
        ):
            with self.subTest(line=line):
                self.assertIsNone(banned_host(self.FILTER, line))

    def test_jail_bans_only_addresses(self):
        # Home Assistant logs the reverse-DNS name next to the address. The
        # filter takes the address, so the jail never needs to resolve a name.
        jail = ROLES / "homeassistant" / "templates" / "fail2ban-jail.conf.j2"
        self.assertRegex(jail.read_text(), r"(?m)^usedns = no$")

    @unittest.skipUnless(shutil.which("fail2ban-regex"), "no fail2ban-regex")
    def test_fail2ban_reads_the_client_address(self):
        forged = f"{self.PREFIX} 192.0.2.1 (192.0.2.1). Requested URL: '/'"
        log = "2026-10-25 12:34:56.789" + self.line(
            "client.example.net", "203.0.113.7", "/auth/token", forged
        )
        self.assertEqual(fail2ban_regex(self.FILTER, log + "\n"), "203.0.113.7\n")


def access_line(
    vhost: str,
    request: str,
    status: int,
    user: str = "-",
    path: str | None = None,
    user_agent: str = "curl",
) -> str:
    # A vhost_combined line as fail2ban sees it, with the timestamp removed.
    # path is %U, the decoded path Apache routes by; by default the request's
    # path without its query string.
    if path is None:
        path = request.split()[1].partition("?")[0]
    return (
        f'{vhost}:443 203.0.113.7 - {user} [] "{request} HTTP/1.1" {status} 28 '
        f'"-" "{user_agent}" 512 "{path}"'
    )


def respelled(method: str, path: str) -> list[tuple[str, str]]:
    """Return request lines that reach path, each with the %U Apache logs.

    %U is decoded, without the query string or dot segments, and with repeated
    slashes merged unless MergeSlashes is off. path must not end in a slash.
    """
    head, _, last = path.rpartition("/")
    encoded = f"{head}/{last[:-1]}%{ord(last[-1]):02X}"
    return [
        (f"{method} {path}", path),
        (f"{method} {path}?", path),
        (f"{method} {path}?x", path),
        (f"{method} {path}?x=1", path),
        (f"{method} /{path}", path),
        (f"{method} /{path}", f"/{path}"),
        (f"{method} /.{path}", path),
        (f"{method} /x/..{path}", path),
        (f"{method} {encoded}", path),
        (f"{method} {path}/", f"{path}/"),
    ]


def render_filter(template: pathlib.Path, directory: str, **variables) -> pathlib.Path:
    """Render a filter template into directory and return the file."""
    environment = jinja2.Environment(
        loader=jinja2.FileSystemLoader(template.parent),
        undefined=jinja2.StrictUndefined,
    )
    environment.filters["comment"] = lambda text: f"#\n# {text}\n#"
    environment.filters["regex_escape"] = re.escape
    text = environment.get_template(template.name).render(
        ansible_managed="Ansible managed", **variables
    )
    path = pathlib.Path(directory) / template.name.removesuffix(".j2")
    path.write_text(text)
    return path


class CouchDBFilterTest(unittest.TestCase):
    FILTER = ROLES / "couchdb" / "files" / "fail2ban-filter.conf"

    def test_counts_a_401_for_any_method(self):
        for method in ("GET", "OPTIONS", "PATCH", "POST", "PROPFIND", "PUT"):
            with self.subTest(method=method):
                line = access_line("couchdb.rewse.jp", f"{method} /_session", 401)
                self.assertEqual(banned_host(self.FILTER, line), "203.0.113.7")

    def test_ignores_other_statuses_and_hosts(self):
        for line in (
            access_line("couchdb.rewse.jp", "PATCH /_session", 405),
            access_line("couchdb.rewse.jp", "GET /db", 200),
            access_line("grafana.rewse.jp", "GET /_session", 401),
        ):
            with self.subTest(line=line):
                self.assertIsNone(banned_host(self.FILTER, line))


class TeslaMateFilterTest(unittest.TestCase):
    FILTER = ROLES / "teslamate" / "files" / "fail2ban-filter.conf"
    VHOST = ROLES / "teslamate" / "templates" / "grafana.rewse.jp.conf.j2"

    def test_counts_a_failed_grafana_login_in_any_spelling(self):
        for request, path in respelled("POST", "/login"):
            with self.subTest(request=request, path=path):
                line = access_line("grafana.rewse.jp", request, 401, path=path)
                self.assertEqual(banned_host(self.FILTER, line), "203.0.113.7")

    def test_ignores_other_grafana_401s(self):
        # A user agent that imitates the %U field; Apache escapes its quotes.
        forged = 'curl\\" 512 \\"/login'
        for line in (
            access_line("grafana.rewse.jp", "GET /api/user", 401),
            access_line("grafana.rewse.jp", "POST /loginx", 401),
            access_line("grafana.rewse.jp", "POST /login/x", 401),
            access_line("grafana.rewse.jp", "POST /login", 200),
            access_line("grafana.rewse.jp", "POST /api/x", 401, user_agent=forged),
            access_line(
                "grafana.rewse.jp", "POST /login/../api/user", 401, path="/api/user"
            ),
        ):
            with self.subTest(line=line):
                self.assertIsNone(banned_host(self.FILTER, line))

    def test_counts_a_teslamate_401_naming_a_user(self):
        named = access_line("teslamate.rewse.jp", "GET /", 401, user="tats")
        anonymous = access_line("teslamate.rewse.jp", "GET /", 401)
        self.assertEqual(banned_host(self.FILTER, named), "203.0.113.7")
        self.assertIsNone(banned_host(self.FILTER, anonymous))

    def test_basic_auth_is_recognised_in_any_case(self):
        # The auth scheme is case-insensitive, and Grafana accepts any case.
        self.assertRegex(
            self.VHOST.read_text(),
            r'(?m)^\s*SetEnvIfNoCase Authorization "\^Basic " grafana_basic_auth$',
        )


class NvrFilterTest(unittest.TestCase):
    TEMPLATE = ROLES / "nvr" / "templates" / "fail2ban-filter.conf.j2"
    HOSTNAME = yaml.safe_load((ROLES / "nvr" / "vars" / "main.yml").read_text())[
        "nvr_hostname"
    ]
    # Each request reaches Frigate's login endpoint. The second field is %U as
    # Apache logs it: decoded, without the query string, and with repeated
    # slashes merged unless MergeSlashes is off.
    LOGINS = (
        ("POST /api/login", "/api/login"),
        ("POST /api/login?x=1", "/api/login"),
        ("POST //api/login", "/api/login"),
        ("POST /api/%6Cogin", "/api/login"),
        ("POST //api/login", "//api/login"),
    )

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.FILTER = render_filter(
            cls.TEMPLATE, cls.tmp.name, nvr_hostname=cls.HOSTNAME
        )

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_counts_a_failed_login_in_any_spelling(self):
        for request, path in self.LOGINS:
            with self.subTest(request=request, path=path):
                line = access_line(self.HOSTNAME, request, 401, path=path)
                self.assertEqual(banned_host(self.FILTER, line), "203.0.113.7")

    def test_ignores_other_requests(self):
        # A user agent that imitates the %U field; Apache escapes its quotes.
        forged = 'curl\\" 512 \\"/api/login'
        for line in (
            access_line(self.HOSTNAME, "POST /api/login", 200),
            access_line(self.HOSTNAME, "GET /api/profile", 401),
            access_line(self.HOSTNAME, "POST /api/logout", 401),
            access_line(self.HOSTNAME, "POST /api/loginx", 401),
            access_line(self.HOSTNAME, "POST /api/events", 401, user_agent=forged),
            access_line("grafana.rewse.jp", "POST /api/login", 401),
        ):
            with self.subTest(line=line):
                self.assertIsNone(banned_host(self.FILTER, line))

    @unittest.skipUnless(shutil.which("fail2ban-regex"), "no fail2ban-regex")
    def test_fail2ban_bans_a_failed_login_in_any_spelling(self):
        lines = [
            access_line(self.HOSTNAME, request, 401, path=path)
            for request, path in self.LOGINS
        ]
        lines.append(access_line(self.HOSTNAME, "POST /api/login?x=1", 200))
        log = "".join(
            line.replace("[]", "[10/Nov/2026:12:34:56 +0900]") + "\n" for line in lines
        )
        self.assertEqual(
            fail2ban_regex(self.FILTER, log), "203.0.113.7\n" * len(self.LOGINS)
        )


class LiteLLMFilterTest(unittest.TestCase):
    FILTER = ROLES / "litellm" / "files" / "fail2ban-filter.conf"
    HOSTNAME = "litellm.rewse.jp"

    def test_counts_a_failed_sign_in_in_any_spelling(self):
        for path in ("/login", "/v2/login"):
            for request, logged in respelled("POST", path):
                with self.subTest(request=request, path=logged):
                    line = access_line(self.HOSTNAME, request, 401, path=logged)
                    self.assertEqual(banned_host(self.FILTER, line), "203.0.113.7")

    def test_ignores_other_requests(self):
        # A user agent that imitates the %U field; Apache escapes its quotes.
        forged = 'curl\\" 512 \\"/login'
        for line in (
            access_line(self.HOSTNAME, "POST /login", 200),
            access_line(self.HOSTNAME, "GET /v1/models", 401),
            access_line(self.HOSTNAME, "POST /loginx", 401),
            access_line(self.HOSTNAME, "POST /mcp", 401, user_agent=forged),
            access_line(self.HOSTNAME, "POST /login/../mcp", 401, path="/mcp"),
            access_line("grafana.rewse.jp", "POST /login", 401),
        ):
            with self.subTest(line=line):
                self.assertIsNone(banned_host(self.FILTER, line))


class McpFilterTest(unittest.TestCase):
    """The mailboxd and zabbix-mcp filters, which both guard /mcp."""

    MCP_ROLES = ("mailboxd", "zabbix_mcp")

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.filters = {}
        for role in cls.MCP_ROLES:
            template = ROLES / role / "templates" / "fail2ban-filter.conf.j2"
            variable = f"{role}_hostname"
            hostname = yaml.safe_load((ROLES / role / "vars" / "main.yml").read_text())[
                variable
            ]
            directory = pathlib.Path(cls.tmp.name) / role
            directory.mkdir()
            path = render_filter(template, str(directory), **{variable: hostname})
            cls.filters[role] = (hostname, path)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_counts_a_rejected_call_in_any_spelling(self):
        requests = respelled("POST", "/mcp") + respelled("GET", "/mcp/x")
        for role, (hostname, path) in self.filters.items():
            for request, logged in requests:
                with self.subTest(role=role, request=request, path=logged):
                    line = access_line(hostname, request, 401, path=logged)
                    self.assertEqual(banned_host(path, line), "203.0.113.7")

    def test_ignores_other_requests(self):
        # A user agent and a path that imitate the %U field; Apache escapes the
        # quotes in both.
        forged_agent = 'curl\\" 512 \\"/mcp'
        for role, (hostname, path) in self.filters.items():
            for line in (
                access_line(hostname, "POST /mcp", 200),
                access_line(hostname, "GET /.well-known/oauth-protected-resource", 401),
                access_line(hostname, "GET /mcpx", 401),
                access_line(
                    hostname,
                    "GET /mcp/../.well-known/oauth-protected-resource",
                    401,
                    path="/.well-known/oauth-protected-resource",
                ),
                access_line(hostname, "GET /x", 401, user_agent=forged_agent),
                access_line(hostname, "GET /x", 401, user_agent="/mcp/x", path="/x"),
                access_line("grafana.rewse.jp", "POST /mcp", 401),
            ):
                with self.subTest(role=role, line=line):
                    self.assertIsNone(banned_host(path, line))


if __name__ == "__main__":
    unittest.main()
