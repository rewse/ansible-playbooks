#!/usr/bin/env python3
"""Regression tests for the Debian javascript-common conf the httpd role disables."""

import pathlib
import unittest

import yaml

HTTPD = pathlib.Path(__file__).resolve().parents[1] / "roles" / "httpd"
ENABLED = "/etc/apache2/conf-enabled/javascript-common.conf"


def conf_tasks() -> list[dict]:
    return yaml.safe_load((HTTPD / "tasks" / "conf.yml").read_text())


def command_of(task: dict) -> str | None:
    command = task.get("ansible.builtin.command")
    if isinstance(command, dict):
        return command.get("cmd")
    return command


class JavascriptCommonTest(unittest.TestCase):
    def disable_tasks(self) -> list[dict]:
        return [
            task
            for task in conf_tasks()
            if command_of(task) == "a2disconf javascript-common"
        ]

    def test_conf_is_disabled_once(self):
        self.assertEqual(len(self.disable_tasks()), 1)

    def test_disable_runs_only_while_enabled(self):
        # The conf may be absent, and a2disconf fails on an unknown conf.
        task = self.disable_tasks()[0]
        self.assertEqual(task["ansible.builtin.command"]["removes"], ENABLED)
        self.assertIn("changed_when", task)

    def test_disable_reloads_apache(self):
        self.assertEqual(self.disable_tasks()[0]["notify"], "Reload Apache")

    def test_no_task_enables_the_conf(self):
        for task in conf_tasks():
            self.assertNotEqual(command_of(task), "a2enconf javascript-common")


if __name__ == "__main__":
    unittest.main()
