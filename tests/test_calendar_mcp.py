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


class CalendarMcpBuildTest(unittest.TestCase):
    def test_lookup_selects_release_commits(self):
        fact = task_named("container.yml", "container | Resolve aged release")[
            "ansible.builtin.set_fact"
        ]
        self.assertIn(
            "github-commit:MarimerLLC/calendar-mcp", fact["__calendar_mcp_source"]
        )
        self.assertIn(r"^Release (\d+\.\d+\.\d+)", fact["__calendar_mcp_source"])

    def test_image_tag_changes_with_the_patch(self):
        # The tag carries the patch checksum, so editing only the patch rebuilds.
        fact = task_named("container.yml", "container | Name image")[
            "ansible.builtin.set_fact"
        ]
        self.assertIn("save-draft.patch", fact["__calendar_mcp_image"])
        self.assertIn("hash('sha256')", fact["__calendar_mcp_image"])

    def test_build_is_skipped_when_the_image_exists(self):
        for name in (
            "container | Check out repository",
            "container | Apply patch",
            "container | Build image",
        ):
            with self.subTest(task=name):
                self.assertIn(
                    "__calendar_mcp_image_info.images",
                    str(task_named("container.yml", name)["when"]),
                )

    def test_patch_failure_stops_the_play(self):
        task = task_named("container.yml", "container | Apply patch")
        self.assertNotIn("ignore_errors", task)
        self.assertNotIn("failed_when", task)

    def test_checkout_starts_clean(self):
        # A forced checkout keeps untracked files, and the patch creates one, so
        # a later version would fail to apply over the leftover file.
        tasks = yaml.safe_load((ROLE / "tasks" / "container.yml").read_text())
        names = [task["name"] for task in tasks]
        remove = task_named("container.yml", "container | Remove previous checkout")
        self.assertEqual(remove["ansible.builtin.file"]["state"], "absent")
        self.assertLess(
            names.index("container | Remove previous checkout"),
            names.index("container | Check out repository"),
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


class CalendarMcpComposeTest(unittest.TestCase):
    def services(self) -> dict:
        text = render(
            "compose.yaml.j2",
            __calendar_mcp_image="calendar-mcp:1.9.0-abc1234-12345678",
        )
        return yaml.safe_load(text)["services"]

    def test_one_service_per_user_on_loopback(self):
        services = self.services()
        self.assertEqual(sorted(services), ["calendar-mcp-ts", "calendar-mcp-ubiqu"])
        self.assertEqual(services["calendar-mcp-ts"]["ports"], ["127.0.0.1:8084:8080"])
        self.assertEqual(
            services["calendar-mcp-ubiqu"]["ports"], ["127.0.0.1:8085:8080"]
        )

    def test_each_service_sees_only_its_own_files(self):
        for name, service in self.services().items():
            user = name.removeprefix("calendar-mcp-")
            with self.subTest(user=user):
                self.assertEqual(
                    service["env_file"], [{"path": f"{user}.env", "format": "raw"}]
                )
                self.assertEqual(
                    service["volumes"],
                    [
                        f"/srv/calendar_mcp/{user}:/app/data",
                        (
                            f"/etc/compose/calendar_mcp/{user}/appsettings.json"
                            ":/app/data/appsettings.json:ro"
                        ),
                    ],
                )

    def test_image_is_the_local_build(self):
        for service in self.services().values():
            self.assertEqual(service["image"], "calendar-mcp:1.9.0-abc1234-12345678")
            self.assertEqual(service["pull_policy"], "never")

    def test_hardening(self):
        for service in self.services().values():
            self.assertEqual(service["cap_drop"], ["ALL"])
            self.assertIs(service["read_only"], True)
            self.assertIn("no-new-privileges:true", service["security_opt"])

    def test_recreate_handler_waits(self):
        handlers = yaml.safe_load((ROLE / "handlers" / "main.yml").read_text())
        recreate = next(h for h in handlers if h["name"] == "Recreate calendar-mcp")
        module = recreate["community.docker.docker_compose_v2"]
        self.assertEqual(module["recreate"], "always")
        self.assertIs(module["wait"], True)

    def test_start_waits_for_each_health_endpoint(self):
        task = task_named("container.yml", "container | Wait for health")
        self.assertIn("/health", task["ansible.builtin.uri"]["url"])
        self.assertEqual(task["loop"], "{{ calendar_mcp_users }}")
        self.assertIn("retries", task)


if __name__ == "__main__":
    unittest.main()
