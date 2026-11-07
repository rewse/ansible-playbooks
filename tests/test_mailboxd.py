#!/usr/bin/env python3
"""Contract tests for the mailboxd role."""

import configparser
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

    def test_recreate_handler_waits_for_healthy(self):
        # The start task checks health before handlers run, so only the
        # handler can catch a configuration that the new container rejects.
        handlers = yaml.safe_load((ROLE / "handlers" / "main.yml").read_text())
        handler = next(h for h in handlers if h["name"] == "Recreate mailboxd")
        compose = handler["community.docker.docker_compose_v2"]
        self.assertIs(compose["wait"], True)
        self.assertEqual(compose["wait_timeout"], 120)


IMAGE = {"ref": "psyb0t/mailbox:v0.8.0@sha256:0"}


def compose() -> dict:
    return yaml.safe_load(render("compose.yaml.j2", __mailboxd_image=IMAGE))


def main_imports() -> dict:
    return {
        task["ansible.builtin.import_tasks"]: task["tags"]
        for task in yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
    }


class MailboxdContainerTest(unittest.TestCase):
    def test_container_listens_on_loopback_only(self):
        self.assertEqual(
            compose()["services"]["mailboxd"]["ports"], ["127.0.0.1:8083:8000"]
        )

    def test_container_runs_the_pinned_image(self):
        self.assertEqual(compose()["services"]["mailboxd"]["image"], IMAGE["ref"])
        self.assertEqual(compose()["name"], "mailboxd")

    def test_container_keeps_the_upstream_hardening(self):
        service = compose()["services"]["mailboxd"]
        self.assertIs(service["read_only"], True)
        self.assertEqual(service["cap_drop"], ["ALL"])
        self.assertIn("no-new-privileges:true", service["security_opt"])
        self.assertIn("healthcheck", service)

    def test_container_reads_secrets_from_the_env_file_only(self):
        service = compose()["services"]["mailboxd"]
        # Raw, so a password with $ or quotes reaches the container unchanged
        # rather than being interpolated by Compose.
        self.assertEqual(service["env_file"], [{"path": ".env", "format": "raw"}])
        self.assertIn(
            "/etc/compose/mailboxd/config.yaml:/etc/mailboxd/config.yaml:ro",
            service["volumes"],
        )
        self.assertIn("/srv/mailboxd:/var/lib/mailboxd", service["volumes"])

    def test_no_watcher_is_deployed(self):
        self.assertEqual(list(compose()["services"]), ["mailboxd"])

    def test_image_is_an_aged_release_tag(self):
        task = task_named("container.yml", "container | Resolve aged image")
        expression = task["ansible.builtin.set_fact"]["__mailboxd_image"]
        self.assertIn("oci:psyb0t/mailbox", expression)
        self.assertIn(r"^v\d+\.\d+\.\d+$", expression)

    def test_compose_change_recreates_the_container(self):
        task = task_named("container.yml", "container | Deploy compose file")
        self.assertEqual(task["notify"], "Recreate mailboxd")

    def test_container_component_is_an_update(self):
        imports = main_imports()
        self.assertEqual(list(imports)[:2], ["config.yml", "container.yml"])
        self.assertEqual(imports["container.yml"], ["mailboxd_container", "update"])


HOSTNAME = "mail-mcp.rewse.jp"


def access_line(vhost: str, request: str, status: int) -> str:
    # A vhost_combined line as fail2ban sees it, with the timestamp removed.
    return f'{vhost}:443 203.0.113.7 - - [] "{request} HTTP/1.1" {status} 28 "-" "curl" 512'


def matches(line: str) -> bool:
    failregex = next(
        entry
        for entry in render("fail2ban-filter.conf.j2").splitlines()
        if entry.startswith("failregex = ")
    )
    regex = re.compile(
        failregex.removeprefix("failregex = ").replace("<HOST>", r"(?P<host>\S+)")
    )
    match = regex.search(line)
    return match is not None and match["host"] == "203.0.113.7"


def jail_section() -> configparser.SectionProxy:
    parser = configparser.ConfigParser(interpolation=None)
    lines = [
        line
        for line in render("fail2ban-jail.conf.j2").splitlines()
        if not line.lstrip().startswith("#")
    ]
    parser.read_string("\n".join(lines))
    return parser["mailboxd"]


class MailboxdApacheTest(unittest.TestCase):
    def test_vhost_proxies_to_loopback_and_streams(self):
        lines = [
            line.strip() for line in render("mail-mcp.rewse.jp.conf.j2").splitlines()
        ]
        for expected in (
            "ServerName mail-mcp.rewse.jp",
            "ProxyPreserveHost on",
            "ProxyPass / http://127.0.0.1:8083/ flushpackets=on",
            "ProxyPassReverse / http://127.0.0.1:8083/",
            "SSLCertificateFile /etc/letsencrypt/live/rewse.jp/fullchain.pem",
        ):
            with self.subTest(line=expected):
                self.assertIn(expected, lines)

    def test_vhost_is_open_to_any_address(self):
        self.assertNotIn("Require ip", render("mail-mcp.rewse.jp.conf.j2"))

    def test_vhost_denies_every_path_but_mcp_and_health(self):
        # mailboxd answers a wrong token with 401 on its whole REST API, but
        # the jail counts only /mcp, so the other paths must not reach it.
        text = render("mail-mcp.rewse.jp.conf.j2")
        match = re.search(
            r'<LocationMatch "(?P<pattern>[^"]+)">\s*Require all denied\s*</LocationMatch>',
            text,
        )
        self.assertIsNotNone(match)
        assert match is not None
        denied = re.compile(match["pattern"])
        for path in (
            "/mailboxes",
            "/messages/1",
            "/mcpx",
            "/healthz",
            "/.well-known/x",
            "/",
        ):
            with self.subTest(path=path):
                self.assertIsNotNone(denied.match(path))
        for path in ("/mcp", "/mcp/", "/health"):
            with self.subTest(path=path):
                self.assertIsNone(denied.match(path))

    def test_role_depends_on_fail2ban_and_httpd(self):
        meta = yaml.safe_load((ROLE / "meta" / "main.yml").read_text())
        self.assertEqual(
            [d["role"] for d in meta["dependencies"]], ["fail2ban", "httpd"]
        )

    def test_components_are_imported_in_order(self):
        imports = main_imports()
        self.assertEqual(
            list(imports),
            ["config.yml", "container.yml", "apache.yml", "fail2ban.yml", "legacy.yml"],
        )
        self.assertEqual(imports["apache.yml"], ["mailboxd_apache"])
        self.assertEqual(imports["fail2ban.yml"], ["mailboxd_fail2ban"])


class MailboxdFail2banTest(unittest.TestCase):
    def test_filter_matches_rejected_mcp_calls(self):
        for request in ("POST /mcp", "POST /mcp/", "GET /mcp", "DELETE /mcp"):
            with self.subTest(request=request):
                self.assertTrue(matches(access_line(HOSTNAME, request, 401)))

    def test_filter_ignores_metadata_success_and_other_vhosts(self):
        for line in (
            # OAuth discovery, which a client may read before it sends a token.
            access_line(HOSTNAME, "GET /.well-known/oauth-protected-resource", 401),
            access_line(HOSTNAME, "POST /mcp", 200),
            access_line(HOSTNAME, "GET /health", 200),
            access_line(HOSTNAME, "GET /mcpx", 401),
            access_line("zabbix-mcp.rewse.jp", "POST /mcp", 401),
        ):
            with self.subTest(line=line):
                self.assertFalse(matches(line))

    def test_jail_reads_the_vhost_log(self):
        jail = jail_section()
        self.assertEqual(jail["enabled"], "true")
        self.assertEqual(jail["backend"], "auto")
        self.assertEqual(jail["filter"], "mailboxd")
        self.assertEqual(jail["logpath"], "/var/log/apache2/other_vhosts_access.log")


class MailboxdPlaybookTest(unittest.TestCase):
    def test_role_runs_on_the_home_primary(self):
        plays = yaml.safe_load((REPO_ROOT / "home-primary.yml").read_text())
        roles = [entry["role"] for play in plays for entry in play.get("roles", [])]
        self.assertIn("mailboxd", roles)
        self.assertLess(roles.index("litellm"), roles.index("mailboxd"))
        self.assertLess(roles.index("mailboxd"), roles.index("matterjs_server"))


class MailboxdLegacyTest(unittest.TestCase):
    @staticmethod
    def tasks() -> list:
        return yaml.safe_load((ROLE / "tasks" / "legacy.yml").read_text())

    @staticmethod
    def removed_paths(tasks):
        for t in tasks:
            module = t.get("ansible.builtin.file")
            if module:
                yield from (
                    t["loop"] if module["path"] == "{{ item }}" else [module["path"]]
                )

    def test_removes_only_calendar_mcp_state(self):
        tasks = self.tasks()
        self.assertEqual(
            sorted(self.removed_paths(tasks)),
            [
                "/etc/apache2/sites-available/calendar-mcp.rewse.jp.conf",
                "/etc/apache2/sites-enabled/calendar-mcp.rewse.jp.conf",
                "/etc/compose/calendar_mcp",
                "/etc/fail2ban/filter.d/calendar_mcp.conf",
                "/etc/fail2ban/jail.d/calendar_mcp.conf",
                "/srv/calendar_mcp",
                "/usr/local/src/calendar-mcp",
            ],
        )
        for t in tasks:
            if "ansible.builtin.file" in t:
                self.assertEqual(t["ansible.builtin.file"]["state"], "absent")

    def test_stops_calendar_mcp_only_while_its_compose_file_exists(self):
        tasks = self.tasks()
        stat = next(t for t in tasks if "ansible.builtin.stat" in t)
        down = next(t for t in tasks if "community.docker.docker_compose_v2" in t)
        self.assertEqual(
            stat["ansible.builtin.stat"]["path"],
            "/etc/compose/calendar_mcp/compose.yaml",
        )
        args = down["community.docker.docker_compose_v2"]
        self.assertEqual(args["project_src"], "/etc/compose/calendar_mcp")
        self.assertEqual(args["state"], "absent")
        self.assertEqual(args["remove_images"], "all")
        self.assertIn(stat["register"], down["when"])
        self.assertLess(
            tasks.index(down),
            min(i for i, t in enumerate(tasks) if "ansible.builtin.file" in t),
        )

    def test_removes_the_dotnet_base_images(self):
        task = next(
            t for t in self.tasks() if "community.docker.docker_image_remove" in t
        )
        self.assertEqual(
            task["community.docker.docker_image_remove"]["name"], "{{ item }}"
        )
        self.assertEqual(
            sorted(task["loop"]),
            [
                "mcr.microsoft.com/dotnet/aspnet:10.0",
                "mcr.microsoft.com/dotnet/sdk:10.0",
            ],
        )

    def test_removes_the_account_after_its_files(self):
        tasks = self.tasks()
        user = next(t for t in tasks if "ansible.builtin.user" in t)
        group = next(t for t in tasks if "ansible.builtin.group" in t)
        self.assertEqual(user["ansible.builtin.user"]["name"], "calendar-mcp")
        self.assertEqual(user["ansible.builtin.user"]["state"], "absent")
        self.assertEqual(group["ansible.builtin.group"]["name"], "calendar-mcp")
        self.assertEqual(group["ansible.builtin.group"]["state"], "absent")
        last_file = max(i for i, t in enumerate(tasks) if "ansible.builtin.file" in t)
        self.assertLess(last_file, tasks.index(user))
        self.assertLess(tasks.index(user), tasks.index(group))

    def test_legacy_is_imported_last(self):
        imports = main_imports()
        self.assertEqual(list(imports)[-1], "legacy.yml")
        self.assertEqual(imports["legacy.yml"], ["mailboxd_legacy"])


if __name__ == "__main__":
    unittest.main()
