#!/usr/bin/env python3
"""Regression tests for services the internet reaches through Apache."""

import configparser
import pathlib
import re
import unittest

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROLES = REPO_ROOT / "roles"
FILEBROWSER = ROLES / "filebrowser"
HOMEASSISTANT = ROLES / "homeassistant"
NVR = ROLES / "nvr"
SECONDARY = ROLES / "homeassistant_ha_secondary"


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
        text = (FILEBROWSER / "templates" / "nas.rewse.jp.conf.j2").read_text()
        self.assertRegex(text, r"(?m)^\s*RequestHeader unset X-Forwarded-For early$")


if __name__ == "__main__":
    unittest.main()
