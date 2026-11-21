#!/usr/bin/env python3
"""Regression tests for applying 1Password passwords to running services.

Grafana and Samba each keep their own copy of a password once an account
exists, so the roles have to re-apply the 1Password value on every run for a
rotation to take effect.
"""

import pathlib
import unittest

import yaml

ROLES = pathlib.Path(__file__).resolve().parents[1] / "roles"


def tasks(path: pathlib.Path) -> list[dict]:
    return yaml.safe_load(path.read_text())


def task_named(path: pathlib.Path, name: str) -> dict:
    for task in tasks(path):
        if task["name"] == name:
            return task
    raise AssertionError(f"{name} not found in {path}")


class GrafanaAdminPasswordTest(unittest.TestCase):
    CONTAINER = ROLES / "teslamate" / "tasks" / "container.yml"
    PROBE = "container | Check Grafana admin password"
    RESET = "container | Apply Grafana admin password"

    def test_password_is_applied_after_the_containers_start(self):
        names = [task["name"] for task in tasks(self.CONTAINER)]
        start = names.index("container | Pull and update containers")
        self.assertGreater(names.index(self.PROBE), start)
        self.assertGreater(names.index(self.RESET), names.index(self.PROBE))

    def test_reset_reads_the_password_from_stdin(self):
        task = task_named(self.CONTAINER, self.RESET)
        exec_args = task["community.docker.docker_container_exec"]
        self.assertEqual(exec_args["container"], "teslamate-grafana")
        self.assertEqual(
            exec_args["argv"],
            [
                "grafana",
                "cli",
                "admin",
                "reset-admin-password",
                "--password-from-stdin",
            ],
        )
        self.assertEqual(exec_args["stdin"], "{{ teslamate_grafana_admin_password }}")
        self.assertNotIn("teslamate_grafana_admin_password", str(exec_args["argv"]))
        self.assertTrue(task["no_log"])

    def test_reset_runs_only_when_the_password_is_rejected(self):
        probe = task_named(self.CONTAINER, self.PROBE)
        uri = probe["ansible.builtin.uri"]
        self.assertEqual(uri["user"], "{{ teslamate_grafana_admin_username }}")
        self.assertEqual(uri["password"], "{{ teslamate_grafana_admin_password }}")
        self.assertTrue(uri["force_basic_auth"])
        self.assertTrue(probe["no_log"])
        reset = task_named(self.CONTAINER, self.RESET)
        self.assertIn(f"{probe['register']}.status == 401", reset["when"])

    def test_check_mode_does_not_reset(self):
        for name in (self.PROBE, self.RESET):
            self.assertIn(
                "not ansible_check_mode", task_named(self.CONTAINER, name)["when"]
            )


class SambaPasswordTest(unittest.TestCase):
    SAMBA = ROLES / "nas" / "tasks" / "samba.yml"
    SET = "samba | Set Samba passwords"

    def test_every_user_is_set_on_every_run(self):
        task = task_named(self.SAMBA, self.SET)
        self.assertNotIn("when", task)
        self.assertEqual(task["loop"], "{{ nas_samba_users }}")
        self.assertIs(task["changed_when"], False)
        self.assertTrue(task["no_log"])

    def test_password_is_passed_on_stdin(self):
        task = task_named(self.SAMBA, self.SET)
        command = task["ansible.builtin.command"]
        self.assertEqual(command["cmd"], "smbpasswd -a -s {{ item }}")
        self.assertIn("nas_samba_password", command["stdin"])

    def test_samba_database_is_not_read(self):
        for task in tasks(self.SAMBA):
            self.assertNotIn("pdbedit", str(task))


if __name__ == "__main__":
    unittest.main()
