#!/usr/bin/env python3
"""Contract tests for the darwin role's sshd component."""

import pathlib
import unittest

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROLE = REPO_ROOT / "roles" / "darwin"
CONFIG = ROLE / "files" / "000-key-only.conf"


def tasks() -> list[dict]:
    return yaml.safe_load((ROLE / "tasks" / "sshd.yml").read_text())


def task(name: str) -> dict:
    return next(t for t in tasks() if t["name"] == name)


def when_text(t: dict) -> str:
    when = t["when"]
    return when if isinstance(when, str) else " and ".join(when)


class SshdTest(unittest.TestCase):
    def test_config_rejects_passwords_and_keyboard_interactive(self):
        lines = [
            line
            for line in CONFIG.read_text().splitlines()
            if line and not line.startswith("#")
        ]
        self.assertEqual(
            lines, ["PasswordAuthentication no", "KbdInteractiveAuthentication no"]
        )

    # sshd keeps the first value it reads, and macOS ships 100-macos.conf.
    def test_config_is_read_before_macos_defaults(self):
        path = yaml.safe_load((ROLE / "vars" / "main.yml").read_text())[
            "darwin_sshd_config_path"
        ]
        self.assertEqual(path, "/etc/ssh/sshd_config.d/000-key-only.conf")
        self.assertLess(pathlib.PurePath(path).name, "100-macos.conf")

    def test_copy_runs_only_when_the_file_differs(self):
        check = task("sshd | Check key-only configuration")
        self.assertEqual(
            check["ansible.builtin.stat"]["path"], "{{ darwin_sshd_config_path }}"
        )
        self.assertEqual(check["ansible.builtin.stat"]["checksum_algorithm"], "sha1")
        self.assertEqual(check["register"], "__darwin_sshd_config")
        copy = task("sshd | Copy key-only configuration")
        self.assertTrue(copy["become"])
        self.assertIn("__darwin_sshd_config.stat.checksum", when_text(copy))
        self.assertIn(
            "lookup('ansible.builtin.file', '000-key-only.conf', rstrip=false)",
            when_text(copy),
        )

    def test_config_is_validated_before_it_is_placed(self):
        copy = task("sshd | Copy key-only configuration")["ansible.builtin.copy"]
        self.assertEqual(copy["validate"], "/usr/sbin/sshd -t -f %s")
        self.assertEqual(
            (copy["src"], copy["dest"], copy["mode"]),
            ("000-key-only.conf", "{{ darwin_sshd_config_path }}", "0644"),
        )
        self.assertEqual((copy["owner"], copy["group"]), ("root", "wheel"))

    def test_keys_are_added_without_removing_others(self):
        keys = task("sshd | Authorize keys")
        module = keys["ansible.posix.authorized_key"]
        self.assertEqual(module["user"], "{{ ansible_facts['user_id'] }}")
        self.assertEqual(module["key"], "{{ item }}")
        self.assertNotIn("exclusive", module)
        self.assertEqual(
            keys["loop"], "{{ darwin_sshd_authorized_keys | default([]) }}"
        )
        self.assertNotIn("become", keys)

    def test_every_task_skips_without_keys(self):
        for t in tasks():
            self.assertIn("darwin_sshd_authorized_keys is defined", when_text(t))

    def test_component_is_imported_with_its_tag(self):
        imports = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
        names = [t["ansible.builtin.import_tasks"] for t in imports]
        self.assertEqual(names[names.index("security.yml") + 1], "sshd.yml")
        self.assertEqual(imports[names.index("sshd.yml")]["tags"], ["darwin_sshd"])

    def test_only_the_personal_mac_lists_keys(self):
        personal = (
            REPO_ROOT / "inventory" / "group_vars" / "darwin_personal" / "darwin.yml"
        )
        comments = [
            key.split()[-1]
            for key in yaml.safe_load(personal.read_text())[
                "darwin_sshd_authorized_keys"
            ]
        ]
        self.assertEqual(comments, ["rex@atom", "rex@chemical"])
        for path in (REPO_ROOT / "inventory").rglob("*.yml"):
            if path != personal:
                self.assertNotIn("darwin_sshd_authorized_keys", path.read_text())


if __name__ == "__main__":
    unittest.main()
