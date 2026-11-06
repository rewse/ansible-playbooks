#!/usr/bin/env python3
"""Contract tests for the calendar_mcp role."""

import json
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
    environment.filters["comment"] = lambda text, style="plain": (
        f"//\n// {text}\n//" if style == "c" else f"#\n# {text}\n#"
    )
    environment.filters["regex_escape"] = re.escape
    environment.filters["to_json"] = json.dumps
    context = {"ansible_managed": "Ansible managed"}
    context.update(
        (key, value) for key, value in role_vars().items() if "{{" not in str(value)
    )
    context.update(overrides)
    return environment.get_template(name).render(**context)


def load_settings(text: str) -> dict:
    """Parse appsettings.json, whose header is a // comment as .NET allows."""
    return json.loads(
        "\n".join(line for line in text.splitlines() if not line.startswith("//"))
    )


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


ACCOUNT = {
    "name": "alice",
    "port": 8084,
    "address": "alice@example.com",
    "sakura_password": "s-pass",
    "apple_id": "alice@icloud.com",
    "apple_password": "aaaa-bbbb-cccc-dddd",
    "token": "t",
    "admin_token": "a",
}
FLAGS = {
    "emailRead",
    "emailSend",
    "calendarRead",
    "calendarWrite",
    "contactsRead",
    "contactsWrite",
}


class CalendarMcpConfigTest(unittest.TestCase):
    def settings(self, account=ACCOUNT) -> dict:
        return load_settings(render("appsettings.json.j2", account=account))[
            "CalendarMcp"
        ]

    def test_exactly_two_accounts_with_explicit_permissions(self):
        accounts = self.settings()["Accounts"]
        self.assertEqual(
            [(a["Id"], a["Provider"]) for a in accounts],
            [("alice-sakura", "imap"), ("alice-icloud", "dav")],
        )
        for account in accounts:
            with self.subTest(account=account["Id"]):
                self.assertEqual(set(account["Permissions"]), FLAGS)
                self.assertIs(account["Permissions"]["emailSend"], False)

    def test_imap_reads_mail_only(self):
        imap = self.settings()["Accounts"][0]
        self.assertEqual(
            {k for k, v in imap["Permissions"].items() if v}, {"emailRead"}
        )
        config = imap["ProviderConfig"]
        self.assertEqual(config["imapHost"], "rewse.sakura.ne.jp")
        self.assertEqual(config["imapPort"], "993")
        self.assertEqual(config["smtpHost"], "smtp.invalid")
        self.assertEqual(config["username"], "alice@example.com")

    def test_imap_uses_the_sakura_folders(self):
        config = self.settings()["Accounts"][0]["ProviderConfig"]
        self.assertEqual(
            (
                config["sentFolder"],
                config["trashFolder"],
                config["junkFolder"],
                config["draftsFolder"],
            ),
            ("INBOX.Sent", "INBOX.Trash", "INBOX.spam", "INBOX.Draft"),
        )

    def test_dav_has_calendar_and_contacts_only(self):
        dav = self.settings()["Accounts"][1]
        self.assertEqual(
            {k for k, v in dav["Permissions"].items() if v},
            {"calendarRead", "calendarWrite", "contactsRead", "contactsWrite"},
        )
        config = dav["ProviderConfig"]
        self.assertEqual(config["preset"], "icloud")
        self.assertEqual(
            (config["enableCalendar"], config["enableContacts"]), ("true", "true")
        )
        self.assertEqual(config["username"], "alice@icloud.com")

    def test_no_router_and_no_admin_sign_in(self):
        root = load_settings(render("appsettings.json.j2", account=ACCOUNT))
        self.assertNotIn("Router", root["CalendarMcp"])
        self.assertNotIn("AdminAuth", root)

    def test_external_url_is_the_https_path(self):
        self.assertEqual(
            self.settings()["ExternalBaseUrl"],
            "https://calendar-mcp.rewse.jp/mcp/alice",
        )

    def test_odd_password_stays_intact(self):
        odd = dict(ACCOUNT, sakura_password='a"b\\c$d', token="x$y")
        imap = self.settings(odd)["Accounts"][0]
        self.assertEqual(imap["ProviderConfig"]["password"], 'a"b\\c$d')
        self.assertIn(
            "CALENDAR_MCP_MCP_KEY=x$y", render("env.j2", account=odd).splitlines()
        )

    def test_env_carries_only_the_two_keys(self):
        lines = [
            line
            for line in render("env.j2", account=ACCOUNT).splitlines()
            if line and not line.startswith("#")
        ]
        self.assertEqual(
            lines, ["CALENDAR_MCP_MCP_KEY=t", "CALENDAR_MCP_ADMIN_TOKEN=a"]
        )

    def test_secret_files_are_private(self):
        settings = task_named("config.yml", "config | Deploy settings")
        self.assertEqual(settings["ansible.builtin.template"]["mode"], "0400")
        self.assertEqual(
            settings["ansible.builtin.template"]["owner"], "{{ calendar_mcp_uid }}"
        )
        env = task_named("config.yml", "config | Deploy environment file")
        self.assertEqual(env["ansible.builtin.template"]["mode"], "0600")
        self.assertEqual(env["ansible.builtin.template"]["owner"], "root")
        for task in (settings, env):
            self.assertTrue(task["no_log"])
            self.assertEqual(task["notify"], "Recreate calendar-mcp")


if __name__ == "__main__":
    unittest.main()
