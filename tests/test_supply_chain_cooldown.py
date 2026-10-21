#!/usr/bin/env python3
"""Regression tests for scheduled jobs that install from PyPI as root."""

import pathlib
import re
import unittest

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROLES = REPO_ROOT / "roles"

CUTOFF = re.compile(
    r"(?m)^UV_EXCLUDE_NEWER=\"\$\(date -u -d '"
    r"(?:\{\{|\[%) supply_chain_cooldown_days (?:\}\}|%\]) days ago' "
    r"\+%Y-%m-%dT%H:%M:%SZ\)\"\nexport UV_EXCLUDE_NEWER$"
)
UV_CALL = re.compile(r"(?m)^(?!\s*#).*\buvx? ")


def template_task(tasks_file: pathlib.Path, dest: str) -> dict:
    tasks = yaml.safe_load(tasks_file.read_text())
    return next(
        t["ansible.builtin.template"]
        for t in tasks
        if t.get("ansible.builtin.template", {}).get("dest") == dest
    )


class TimerCooldownTest(unittest.TestCase):
    def assert_cooldown_precedes_uv(self, script: pathlib.Path):
        # The timer runs between playbook runs, so the cutoff that
        # supply_chain_cooldown_environment gives a task is computed in the
        # script on each run instead.
        text = script.read_text()
        cutoff = CUTOFF.search(text)
        self.assertIsNotNone(cutoff, "no UV_EXCLUDE_NEWER cutoff")
        assert cutoff is not None
        calls = [m.start() for m in UV_CALL.finditer(text)]
        self.assertTrue(calls, "no uv call")
        self.assertLess(cutoff.end(), min(calls))

    def test_certbot_renew_applies_the_cooldown(self):
        role = ROLES / "sslcert"
        task = template_task(
            role / "tasks" / "certbot.yml", "/usr/local/sbin/certbot-renew"
        )
        self.assertEqual(task["src"], "certbot-renew.j2")
        self.assertFalse((role / "files" / "certbot-renew").exists())
        self.assert_cooldown_precedes_uv(role / "templates" / "certbot-renew.j2")

    def test_enecoq_data_fetcher_applies_the_cooldown(self):
        role = ROLES / "enecoq_data_fetcher"
        script = role / "templates" / "enecoq-data-fetcher.j2"
        self.assert_cooldown_precedes_uv(script)
        # The package is this account's own and is adopted without a cooldown;
        # its third-party dependencies, such as playwright, are not.
        for line in script.read_text().splitlines():
            if re.match(r"\s*uvx ", line):
                with self.subTest(line=line):
                    self.assertIn('--exclude-newer-package "$OWN_PACKAGE"', line)


if __name__ == "__main__":
    unittest.main()
