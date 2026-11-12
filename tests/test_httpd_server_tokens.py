#!/usr/bin/env python3
"""Regression tests for the Apache server identification the httpd role sets."""

import pathlib
import re
import unittest

import yaml

HTTPD = pathlib.Path(__file__).resolve().parents[1] / "roles" / "httpd"
CONF = HTTPD / "files" / "server-tokens.conf"


def conf_tasks() -> list[dict]:
    return yaml.safe_load((HTTPD / "tasks" / "conf.yml").read_text())


class ServerTokensTest(unittest.TestCase):
    def test_reports_only_the_product_name(self):
        self.assertEqual(
            re.findall(r"(?m)^\s*ServerTokens\s+(\S+)", CONF.read_text()), ["Prod"]
        )

    def test_omits_the_signature_footer(self):
        self.assertEqual(
            re.findall(r"(?m)^\s*ServerSignature\s+(\S+)", CONF.read_text()), ["Off"]
        )

    def test_loads_after_ubuntu_security_conf(self):
        # Apache applies the last ServerTokens and ServerSignature it reads, and
        # includes conf-enabled/*.conf in sorted order.
        self.assertGreater(CONF.name, "security.conf")

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
            if task.get("ansible.builtin.command") == "a2enconf server-tokens"
        ]
        self.assertEqual(len(enables), 1)
        self.assertEqual(enables[0]["notify"], "Reload Apache")
        self.assertIn("changed_when", enables[0])


if __name__ == "__main__":
    unittest.main()
