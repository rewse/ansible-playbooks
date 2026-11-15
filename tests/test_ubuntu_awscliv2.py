#!/usr/bin/env python3
"""Contract tests for the ubuntu role's AWS CLI v2 component."""

import pathlib
import unittest

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
TASKS = REPO_ROOT / "roles" / "ubuntu" / "tasks" / "awscliv2.yml"


def task(name: str) -> dict:
    tasks = yaml.safe_load(TASKS.read_text())
    return next(t for t in tasks if t["name"] == name)


class AwsCliV2Test(unittest.TestCase):
    def test_every_run_downloads_the_latest_installer(self):
        download = task("awscliv2 | Download and extract")
        self.assertNotIn("when", download)
        self.assertEqual(
            download["ansible.builtin.unarchive"]["dest"], "/usr/local/src"
        )

    def test_an_installed_cli_is_updated_from_that_installer(self):
        update = task("awscliv2 | Update")
        self.assertEqual(
            update["ansible.builtin.command"], "/usr/local/src/aws/install --update"
        )
        self.assertEqual(update["when"], "__ubuntu_aws.stat.exists")


if __name__ == "__main__":
    unittest.main()
