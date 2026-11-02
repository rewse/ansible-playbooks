#!/usr/bin/env python3
"""Contract tests for the mailboxd role."""

import pathlib
import re
import unittest

import jinja2
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROLE = REPO_ROOT / "roles" / "mailboxd"

MAILBOXES = [
    {
        "name": "alice",
        "address": "alice@example.com",
        "password": "alice-password",
        "token": "alice-token",
    },
    {
        "name": "bob",
        "address": "bob@example.com",
        "password": "bob-password",
        "token": "bob-token",
    },
]


def role_vars() -> dict:
    return yaml.safe_load((ROLE / "vars" / "main.yml").read_text())


def render(name: str, **overrides) -> str:
    environment = jinja2.Environment(
        loader=jinja2.FileSystemLoader(ROLE / "templates"),
        undefined=jinja2.StrictUndefined,
    )
    environment.filters["comment"] = lambda text: f"#\n# {text}\n#"
    environment.filters["regex_escape"] = re.escape
    context = {
        "__mailboxd_mailboxes": MAILBOXES,
        "ansible_managed": "Ansible managed",
        "mailboxd_trusted_authserv_id": "",
    }
    context.update(
        (key, value) for key, value in role_vars().items() if isinstance(value, int)
    )
    context.update(
        (key, value)
        for key, value in role_vars().items()
        if isinstance(value, str) and "{{" not in value
    )
    context.update(overrides)
    return environment.get_template(name).render(**context)


def task_named(file: str, name: str) -> dict:
    tasks = yaml.safe_load((ROLE / "tasks" / file).read_text())
    return next(task for task in tasks if task["name"] == name)


class MailboxdConfigTest(unittest.TestCase):
    def test_every_token_is_limited_to_its_own_mailbox(self):
        tokens = yaml.safe_load(render("config.yaml.j2"))["auth"]["tokens"]
        self.assertEqual([t["mailboxes"] for t in tokens], [["alice"], ["bob"]])
        for token in tokens:
            self.assertIsInstance(token, dict)
            self.assertEqual(token["scopes"], ["read", "draft", "organize"])

    def test_sending_cannot_reach_a_server(self):
        config = yaml.safe_load(render("config.yaml.j2"))
        self.assertIs(config["send_guard"]["dry_run"], True)
        for mailbox in config["mailboxes"]:
            self.assertEqual(mailbox["smtp"]["host"], "smtp.invalid")
            self.assertNotIn("${", mailbox["smtp"]["password"])

    def test_imap_points_at_sakura_over_tls(self):
        imap = yaml.safe_load(render("config.yaml.j2"))["mailboxes"][0]["imap"]
        self.assertEqual(
            (imap["host"], imap["port"], imap["tls"]),
            ("rewse.sakura.ne.jp", 993, "ssl"),
        )
        self.assertEqual(imap["username"], "alice@example.com")
        self.assertEqual(imap["password"], "${MAILBOXD_PASSWORD_ALICE}")

    def test_config_holds_no_secret(self):
        text = render("config.yaml.j2")
        for mailbox in MAILBOXES:
            with self.subTest(mailbox=mailbox["name"]):
                self.assertNotIn(mailbox["password"], text)
                self.assertNotIn(mailbox["token"], text)

    def test_env_file_carries_the_secrets(self):
        lines = [
            line
            for line in render("env.j2").splitlines()
            if line and not line.startswith("#")
        ]
        env = dict(line.split("=", 1) for line in lines)
        self.assertEqual(env["MAILBOXD_TOKEN_ALICE"], "alice-token")
        self.assertEqual(env["MAILBOXD_PASSWORD_BOB"], "bob-password")

    def test_env_names_fold_hyphens_into_underscores(self):
        mailbox = dict(MAILBOXES[0], name="jo-ann")
        config = yaml.safe_load(
            render("config.yaml.j2", __mailboxd_mailboxes=[mailbox])
        )
        self.assertEqual(
            config["auth"]["tokens"][0]["token"], "${MAILBOXD_TOKEN_JO_ANN}"
        )
        self.assertIn(
            "MAILBOXD_TOKEN_JO_ANN=alice-token",
            render("env.j2", __mailboxd_mailboxes=[mailbox]).splitlines(),
        )

    def test_trusted_authserv_id_is_omitted_until_known(self):
        self.assertNotIn(
            "trusted_authserv_id", yaml.safe_load(render("config.yaml.j2"))["auth"]
        )
        config = yaml.safe_load(
            render("config.yaml.j2", mailboxd_trusted_authserv_id="mx.example.com")
        )
        self.assertEqual(config["auth"]["trusted_authserv_id"], "mx.example.com")

    def test_env_file_is_root_only_and_recreates_the_container(self):
        task = task_named("config.yml", "config | Deploy environment file")
        self.assertEqual(task["ansible.builtin.template"]["mode"], "0600")
        self.assertEqual(task["notify"], "Recreate mailboxd")
        self.assertTrue(task["no_log"])

    def test_config_change_recreates_the_container(self):
        task = task_named("config.yml", "config | Deploy configuration file")
        self.assertEqual(task["notify"], "Recreate mailboxd")

    def test_recreate_handler_rereads_the_env_file(self):
        handlers = yaml.safe_load((ROLE / "handlers" / "main.yml").read_text())
        handler = next(h for h in handlers if h["name"] == "Recreate mailboxd")
        compose = handler["community.docker.docker_compose_v2"]
        self.assertEqual(compose["state"], "present")
        self.assertEqual(compose["recreate"], "always")


if __name__ == "__main__":
    unittest.main()
