#!/usr/bin/env python3
"""Regression tests for services the internet reaches through Apache."""

import configparser
import pathlib
import re
import subprocess
import tempfile
import time
import unittest

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROLES = REPO_ROOT / "roles"
AUTODISCOVER = ROLES / "autodiscover"
FAIL2BAN = ROLES / "fail2ban"
FILEBROWSER = ROLES / "filebrowser"
HTTPD = ROLES / "httpd"
HOMEASSISTANT = ROLES / "homeassistant"
NVR = ROLES / "nvr"
POSTFIX_CLIENT = ROLES / "postfix_client"
SECONDARY = ROLES / "homeassistant_ha_secondary"
TESLAMATE = ROLES / "teslamate"


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


def access_line(vhost: str, request: str, status: int) -> str:
    # A vhost_combined line as fail2ban sees it, with the timestamp removed.
    return f'{vhost}:443 203.0.113.7 - - [] "{request} HTTP/1.1" {status} 28 "-" "curl"'


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
            (SECONDARY / "files" / "homeassistant-sync").read_text(),
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


class FileBrowserForwardedForTest(unittest.TestCase):
    def test_vhost_drops_client_forwarded_for(self):
        # FileBrowser trusts X-Forwarded-For for its lockout and audit log, and
        # mod_proxy appends to a header the client sent rather than replacing it.
        # The unset runs in fixups, after mod_remoteip restores the client
        # address; an early unset races mod_remoteip in post_read_request.
        text = (FILEBROWSER / "templates" / "nas.rewse.jp.conf.j2").read_text()
        self.assertRegex(text, r"(?m)^\s*RequestHeader unset X-Forwarded-For$")
        self.assertNotRegex(text, r"(?m)^\s*RequestHeader unset X-Forwarded-For early")


class GrafanaCookieTest(unittest.TestCase):
    def test_session_cookie_is_sent_over_https_only(self):
        # Sessions last ten years, and a cookie without Secure also goes out
        # with any plain http:// request to the name, before a redirect.
        text = (TESLAMATE / "templates" / "grafana.env.j2").read_text()
        self.assertRegex(text, r"(?m)^GF_SECURITY_COOKIE_SECURE=true$")


class InternetTlsVerificationTest(unittest.TestCase):
    # Both legs cross the internet carrying credentials, so an unverified peer
    # lets an on-path attacker collect them.
    CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"

    def test_postfix_verifies_the_relay(self):
        lines = {
            task["ansible.builtin.lineinfile"]["line"]
            for task in load_yaml(POSTFIX_CLIENT / "tasks" / "main_cf.yml")
        }
        self.assertIn("smtp_tls_security_level = secure", lines)
        # Read before the smtp client enters its chroot, unlike smtp_tls_CApath.
        self.assertIn(f"smtp_tls_CAfile = {self.CA_BUNDLE}", lines)

    def test_autodiscover_proxy_verifies_workmail(self):
        text = (AUTODISCOVER / "files" / "autodiscover.conf").read_text()
        self.assertRegex(text, r"(?m)^SSLProxyVerify require$")
        # The default depth of 1 rejects WorkMail's leaf + intermediate chain.
        self.assertRegex(text, r"(?m)^SSLProxyVerifyDepth [3-9]$")
        self.assertRegex(text, rf"(?m)^SSLProxyCACertificateFile {self.CA_BUNDLE}$")
        self.assertNotRegex(text, r"(?m)^SSLProxyCheckPeer\w+ off$")


class SecurityAgentPentestTest(unittest.TestCase):
    # AWS Security Agent pentests send a secret header so that fail2ban, which
    # would otherwise ban them from every service on the host within seconds,
    # ignores their address. Apache records which addresses sent it.
    LOG_LINE = (
        "CustomLog ${APACHE_LOG_DIR}/security_agent_pentest.log "
        '"%{sec}t %a" env=security_agent_pentest'
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
        self.assertRegex(
            text,
            r'(?m)^SetEnvIf X-Security-Agent-Pentest "\^\{\{ '
            r'httpd_security_agent_pentest_token \}\}\$" security_agent_pentest$',
        )
        # Not "early": that runs before SetEnvIf reads the header.
        self.assertRegex(text, r"(?m)^RequestHeader unset X-Security-Agent-Pentest$")
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
