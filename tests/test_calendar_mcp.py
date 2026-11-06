#!/usr/bin/env python3
"""Contract tests for the calendar_mcp role."""

import pathlib
import re
import unittest

import jinja2
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROLE = REPO_ROOT / "roles" / "calendar_mcp"


def role_vars() -> dict:
    return yaml.safe_load((ROLE / "vars" / "main.yml").read_text())


def render(name: str, **overrides) -> str:
    environment = jinja2.Environment(
        loader=jinja2.FileSystemLoader(ROLE / "templates"),
        undefined=jinja2.StrictUndefined,
    )
    environment.filters["comment"] = lambda text: f"#\n# {text}\n#"
    environment.filters["regex_escape"] = re.escape
    context = {"ansible_managed": "Ansible managed"}
    context.update(
        (key, value) for key, value in role_vars().items() if "{{" not in str(value)
    )
    context.update(overrides)
    return environment.get_template(name).render(**context)


def task_named(file: str, name: str) -> dict:
    tasks = yaml.safe_load((ROLE / "tasks" / file).read_text())
    return next(task for task in tasks if task["name"] == name)


class CalendarMcpSourceTest(unittest.TestCase):
    def test_lookup_selects_release_commits(self):
        fact = task_named("source.yml", "source | Resolve aged release")[
            "ansible.builtin.set_fact"
        ]
        self.assertIn(
            "github-commit:MarimerLLC/calendar-mcp", fact["__calendar_mcp_source"]
        )
        self.assertIn(r"^Release (\d+\.\d+\.\d+)", fact["__calendar_mcp_source"])

    def test_image_tag_changes_with_the_patch(self):
        # The tag carries the patch checksum, so editing only the patch rebuilds.
        fact = task_named("source.yml", "source | Name image")[
            "ansible.builtin.set_fact"
        ]
        self.assertIn("save-draft.patch", fact["__calendar_mcp_image"])
        self.assertIn("hash('sha256')", fact["__calendar_mcp_image"])

    def test_build_is_skipped_when_the_image_exists(self):
        for name in (
            "source | Check out repository",
            "source | Apply patch",
            "source | Build image",
        ):
            with self.subTest(task=name):
                self.assertIn(
                    "__calendar_mcp_image_info.images",
                    str(task_named("source.yml", name)["when"]),
                )

    def test_patch_failure_stops_the_play(self):
        task = task_named("source.yml", "source | Apply patch")
        self.assertNotIn("ignore_errors", task)
        self.assertNotIn("failed_when", task)

    def test_checkout_starts_clean(self):
        # A forced checkout keeps untracked files, and the patch creates one, so
        # a later version would fail to apply over the leftover file.
        tasks = yaml.safe_load((ROLE / "tasks" / "source.yml").read_text())
        names = [task["name"] for task in tasks]
        remove = task_named("source.yml", "source | Remove previous checkout")
        self.assertEqual(remove["ansible.builtin.file"]["state"], "absent")
        self.assertLess(
            names.index("source | Remove previous checkout"),
            names.index("source | Check out repository"),
        )

    def test_users_and_ports(self):
        users = role_vars()["calendar_mcp_users"]
        self.assertEqual([u["name"] for u in users], ["ts", "ubiqu"])
        self.assertEqual([u["port"] for u in users], [8084, 8085])


if __name__ == "__main__":
    unittest.main()
