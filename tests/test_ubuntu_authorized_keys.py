#!/usr/bin/env python3
"""Contract tests for the admin's authorized_keys in the ubuntu role."""

import base64
import pathlib
import unittest

import jinja2
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
TASKS = REPO_ROOT / "roles" / "ubuntu" / "tasks" / "user.yml"
BASE = "ssh-ed25519 AAAA1 mac\nssh-ed25519 AAAA2 ubuntu\n"


def task(name: str) -> dict:
    tasks = yaml.safe_load(TASKS.read_text())
    return next(t for t in tasks if t["name"] == name)


def render(base: str, extra: list[str] | None) -> str:
    environment = jinja2.Environment()
    environment.filters["b64decode"] = lambda s: base64.b64decode(s).decode()
    context: dict = {
        "__ubuntu_authorized_keys": {
            "content": base64.b64encode(base.encode()).decode()
        }
    }
    if extra is not None:
        context["ubuntu_admin_extra_authorized_keys"] = extra
    write = task("user | Write authorized_keys for admin")
    for key, value in write.get("vars", {}).items():
        context[key] = environment.from_string(value).render(context)
    return environment.from_string(write["ansible.builtin.copy"]["content"]).render(
        context
    )


class AdminAuthorizedKeysTest(unittest.TestCase):
    def test_without_extra_keys_the_file_equals_ubuntu_keys(self):
        self.assertEqual(render(BASE, None), BASE)
        self.assertEqual(render(BASE, []), BASE)
        self.assertEqual(
            render("ssh-ed25519 AAAA1 mac", []), "ssh-ed25519 AAAA1 mac"
        )

    def test_extra_keys_follow_ubuntu_keys(self):
        self.assertEqual(
            render(BASE, ["ssh-ed25519 BBBB1 iphone", "ssh-ed25519 BBBB2 ipad"]),
            BASE + "ssh-ed25519 BBBB1 iphone\nssh-ed25519 BBBB2 ipad\n",
        )

    def test_extra_keys_start_on_their_own_line(self):
        self.assertEqual(
            render("ssh-ed25519 AAAA1 mac", ["ssh-ed25519 BBBB1 iphone"]),
            "ssh-ed25519 AAAA1 mac\nssh-ed25519 BBBB1 iphone\n",
        )

    def test_keys_are_read_from_ubuntu_and_written_to_admin(self):
        read = task("user | Read authorized_keys of ubuntu")
        self.assertEqual(
            read["ansible.builtin.slurp"]["src"], "/home/ubuntu/.ssh/authorized_keys"
        )
        self.assertEqual(read["register"], "__ubuntu_authorized_keys")
        write = task("user | Write authorized_keys for admin")["ansible.builtin.copy"]
        self.assertEqual(write["dest"], "/home/{{ admin_user }}/.ssh/authorized_keys")
        self.assertEqual(write["mode"], "0600")
        self.assertEqual(
            (write["owner"], write["group"]), ("{{ admin_user }}", "{{ admin_user }}")
        )
        self.assertNotIn("remote_src", write)


if __name__ == "__main__":
    unittest.main()
