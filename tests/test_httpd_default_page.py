#!/usr/bin/env python3
"""Tests for the stock Ubuntu page the httpd role removes from the default site."""

import pathlib
import unittest

import yaml

HTTPD = pathlib.Path(__file__).resolve().parents[1] / "roles" / "httpd"
PAGE = "/srv/www/html/index.html"


def default_site_tasks() -> list[dict]:
    return yaml.safe_load((HTTPD / "tasks" / "default_site.yml").read_text())


class DefaultPageTest(unittest.TestCase):
    def removal_tasks(self) -> list[dict]:
        return [
            task
            for task in default_site_tasks()
            if (task.get("ansible.builtin.file") or {}).get("path") == PAGE
        ]

    def test_stock_page_is_removed_once(self):
        tasks = self.removal_tasks()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["ansible.builtin.file"]["state"], "absent")

    def test_document_root_itself_is_kept(self):
        # /srv/www/html/admin lives under the same document root.
        for task in default_site_tasks():
            module = task.get("ansible.builtin.file") or {}
            if module.get("state") == "absent":
                self.assertNotIn(module.get("path"), ("/srv/www/html", "/var/www/html"))


if __name__ == "__main__":
    unittest.main()
