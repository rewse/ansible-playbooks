"""Regression tests for the postfix_client role."""

import pathlib
import unittest

import jinja2
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROLE = REPO_ROOT / "roles" / "postfix_client"


def main_cf_tasks() -> list[dict]:
    return yaml.safe_load((ROLE / "tasks" / "main_cf.yml").read_text())


def submit_users_task() -> dict:
    for task in main_cf_tasks():
        lineinfile = task.get("ansible.builtin.lineinfile", {})
        if lineinfile.get("regexp", "").startswith("^authorized_submit_users"):
            return task
    raise AssertionError("main_cf.yml does not set authorized_submit_users")


def rendered_submit_users() -> list[str]:
    line = submit_users_task()["ansible.builtin.lineinfile"]["line"]
    rendered = (
        jinja2.Environment(undefined=jinja2.StrictUndefined)
        .from_string(line)
        .render(admin_user="tats")
    )
    name, _, value = rendered.partition("=")
    assert name.strip() == "authorized_submit_users", rendered
    return [entry.strip() for entry in value.replace(",", " ").split()]


class AuthorizedSubmitUsersTest(unittest.TestCase):
    def test_allows_only_root_and_admin_user(self) -> None:
        self.assertEqual(sorted(rendered_submit_users()), ["root", "tats"])

    def test_uses_no_lookup_table(self) -> None:
        # A table such as static:<name> answers every lookup key, so it would
        # authorize every local account instead of the named one.
        for entry in rendered_submit_users():
            self.assertNotIn(":", entry)
            self.assertFalse(entry.startswith("/"), entry)
            self.assertFalse(entry.startswith("!"), entry)

    def test_targets_main_cf_and_reloads_postfix(self) -> None:
        task = submit_users_task()
        self.assertEqual(
            task["ansible.builtin.lineinfile"]["dest"], "/etc/postfix/main.cf"
        )
        self.assertEqual(task["notify"], "Reload postfix")


if __name__ == "__main__":
    unittest.main()
