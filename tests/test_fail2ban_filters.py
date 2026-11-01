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


if __name__ == "__main__":
    unittest.main()
