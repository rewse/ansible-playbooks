#!/usr/bin/env python3
"""Regression tests for the fail2ban filters of the services on fox."""

import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

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

    @unittest.skipUnless(shutil.which("fail2ban-regex"), "no fail2ban-regex")
    def test_fail2ban_reads_the_client_address(self):
        forged = f"{self.PREFIX} 192.0.2.1 (192.0.2.1). Requested URL: '/'"
        log = "2026-10-25 12:34:56.789" + self.line(
            "client.example.net", "203.0.113.7", "/auth/token", forged
        )
        self.assertEqual(fail2ban_regex(self.FILTER, log + "\n"), "203.0.113.7\n")


def access_line(vhost: str, request: str, status: int, user: str = "-") -> str:
    # A vhost_combined line as fail2ban sees it, with the timestamp removed.
    return (
        f'{vhost}:443 203.0.113.7 - {user} [] "{request} HTTP/1.1" {status} 28 '
        '"-" "curl" 512'
    )


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

    def test_counts_a_failed_grafana_login(self):
        for request in ("POST /login", "POST /login?x=1", "POST /login?"):
            with self.subTest(request=request):
                line = access_line("grafana.rewse.jp", request, 401)
                self.assertEqual(banned_host(self.FILTER, line), "203.0.113.7")

    def test_ignores_other_grafana_401s(self):
        for request in ("GET /api/user", "POST /loginx", "POST /login/x"):
            with self.subTest(request=request):
                line = access_line("grafana.rewse.jp", request, 401)
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


if __name__ == "__main__":
    unittest.main()
