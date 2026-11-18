#!/usr/bin/env python3
"""Regression tests for the control character check the httpd role sets."""

import pathlib
import re
import unittest
import urllib.parse

import yaml

HTTPD = pathlib.Path(__file__).resolve().parents[1] / "roles" / "httpd"
CONF = HTTPD / "files" / "control-chars.conf"


def conf_tasks() -> list[dict]:
    return yaml.safe_load((HTTPD / "tasks" / "conf.yml").read_text())


def if_sections() -> list[tuple[str, str]]:
    """Return the condition and the body of each If section in the conf."""
    return re.findall(r'(?ms)^<If "(.*?)">\n(.*?)^</If>$', CONF.read_text())


def refused(path: str) -> bool:
    """Return whether the conf refuses a request for the encoded path.

    Apache tests REQUEST_URI, the path it routes and proxies by, after it has
    decoded the percent escapes and before it adds the query string.
    """
    decoded = urllib.parse.unquote(path.partition("?")[0])
    for condition, _ in if_sections():
        match = re.fullmatch(r"%\{REQUEST_URI\} =~ /(.*)/", condition)
        assert match is not None, condition
        if re.search(match[1], decoded):
            return True
    return False


class ControlCharsTest(unittest.TestCase):
    def test_refuses_with_bad_request(self):
        sections = if_sections()
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0][1].strip(), "Redirect 400")

    def test_refuses_a_path_with_a_control_character(self):
        for path in (
            "/api/login%0a",
            "/api/login%0A",
            "/api/login%0d",
            "/api/login%0d%0a",
            "/api/login%09",
            "/api/login%1b",
            "/api/login%1f",
            "/api/login%7f",
            "/api/lo%0agin",
            "/api/login%0a?x=1",
        ):
            with self.subTest(path=path):
                self.assertTrue(refused(path))

    def test_passes_other_paths(self):
        for path in (
            "/",
            "/api/login",
            "/api/%6Cogin",
            "/api/login%20x",
            "/api/login?x=%0a",
            "/files/%E3%81%82.txt",
            "/files/%C2%85",
            "/files/~user/a%2Bb",
        ):
            with self.subTest(path=path):
                self.assertFalse(refused(path))

    def test_conf_is_copied_and_enabled(self):
        tasks = conf_tasks()
        copies = [
            task
            for task in tasks
            if task.get("ansible.builtin.copy", {}).get("src") == CONF.name
        ]
        self.assertEqual(len(copies), 1)
        self.assertEqual(
            copies[0]["ansible.builtin.copy"]["dest"], "/etc/apache2/conf-available"
        )
        self.assertEqual(copies[0]["notify"], "Reload Apache")
        enables = [
            task
            for task in tasks
            if task.get("ansible.builtin.command") == "a2enconf control-chars"
        ]
        self.assertEqual(len(enables), 1)
        self.assertEqual(enables[0]["notify"], "Reload Apache")
        self.assertIn("changed_when", enables[0])


if __name__ == "__main__":
    unittest.main()
