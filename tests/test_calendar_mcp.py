#!/usr/bin/env python3
"""Contract tests for the calendar_mcp role."""

import configparser
import hashlib
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


def render_expression(expression: str, **facts) -> str:
    """Render a set_fact expression as Ansible would, with the facts given."""
    environment = jinja2.Environment(undefined=jinja2.StrictUndefined)
    environment.filters["hash"] = lambda text, algorithm: hashlib.new(
        algorithm, text.encode()
    ).hexdigest()
    return environment.from_string(expression).render(**facts)


# Distinct numbers, so a field that reads the other variable shows up.
ACCOUNT_IDS = {"calendar_mcp_uid": 1980, "calendar_mcp_gid": 1981}


def resolved(expression) -> str:
    """Render a task argument with the role vars and ACCOUNT_IDS."""
    return render_expression(str(expression), **(role_vars() | ACCOUNT_IDS))


class CalendarMcpBuildTest(unittest.TestCase):
    def test_depends_on_the_docker_role(self):
        # The role sorts before docker in home-primary.yml, and --tags
        # calendar_mcp alone must still install Docker and buildx first.
        meta = yaml.safe_load((ROLE / "meta" / "main.yml").read_text())
        roles = [dependency["role"] for dependency in meta["dependencies"]]
        self.assertIn("docker", roles)

    def test_lookup_follows_the_fork_without_cooldown(self):
        fact = task_named("container.yml", "container | Resolve fork commit")[
            "ansible.builtin.set_fact"
        ]["__calendar_mcp_source"]
        self.assertIn("github-commit:rewse/calendar-mcp", fact)
        self.assertIn("days=0", fact)

    def test_image_tag_joins_the_commit_and_the_base_images(self):
        expression = task_named("container.yml", "container | Name image")[
            "ansible.builtin.set_fact"
        ]["__calendar_mcp_image"]
        sdk = "mcr.microsoft.com/dotnet/sdk:10.0.402@sha256:aaa"
        runtime = "mcr.microsoft.com/dotnet/aspnet:10.0.13@sha256:bbb"
        tag = render_expression(
            expression,
            __calendar_mcp_source={
                "commit": "08680d87ba0918b8e10c3302ce6c02b58516b94b"
            },
            __calendar_mcp_sdk_image={"ref": sdk},
            __calendar_mcp_runtime_image={"ref": runtime},
        )
        self.assertEqual(
            tag,
            "calendar-mcp:08680d87ba09-"
            + hashlib.sha256(f"{sdk} {runtime}".encode()).hexdigest()[:12],
        )

    def test_base_images_are_aged_releases_of_the_target_framework(self):
        for name, var, repo in (
            (
                "container | Resolve SDK image",
                "__calendar_mcp_sdk_image",
                "oci:mcr.microsoft.com/dotnet/sdk",
            ),
            (
                "container | Resolve runtime image",
                "__calendar_mcp_runtime_image",
                "oci:mcr.microsoft.com/dotnet/aspnet",
            ),
        ):
            with self.subTest(name=name):
                fact = task_named("container.yml", name)["ansible.builtin.set_fact"][
                    var
                ]
                self.assertIn(repo, fact)
                self.assertIn("calendar_mcp_container_dotnet_version", fact)
                # The default supply-chain cooldown applies.
                self.assertNotIn("days=", fact)
        self.assertEqual(role_vars()["calendar_mcp_container_dotnet_version"], "10.0")

    def test_build_passes_the_pinned_base_images(self):
        build = task_named("container.yml", "container | Build image")[
            "community.docker.docker_image_build"
        ]
        self.assertEqual(
            build["args"],
            {
                "SDK_IMAGE": "{{ __calendar_mcp_sdk_image.ref }}",
                "RUNTIME_IMAGE": "{{ __calendar_mcp_runtime_image.ref }}",
            },
        )

    def test_checkout_is_the_fork(self):
        git = task_named("container.yml", "container | Check out repository")[
            "ansible.builtin.git"
        ]
        self.assertEqual(git["repo"], "https://github.com/rewse/calendar-mcp.git")
        self.assertIs(git["force"], True)

    def test_no_patch_is_applied(self):
        self.assertNotIn(
            "ansible.posix.patch", (ROLE / "tasks" / "container.yml").read_text()
        )
        self.assertFalse((ROLE / "files" / "calendar-mcp.patch").exists())

    def test_build_is_skipped_when_the_image_exists(self):
        for name in (
            "container | Check out repository",
            "container | Build image",
        ):
            with self.subTest(task=name):
                self.assertIn(
                    "__calendar_mcp_image_info.images",
                    str(task_named("container.yml", name)["when"]),
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


class CalendarMcpUserTest(unittest.TestCase):
    def test_account_is_a_system_account_without_login(self):
        group = task_named("user.yml", "user | Create system group")[
            "ansible.builtin.group"
        ]
        user = task_named("user.yml", "user | Create system user")[
            "ansible.builtin.user"
        ]
        self.assertEqual(group["name"], "calendar-mcp")
        self.assertTrue(group["system"])
        self.assertEqual(resolved(group["gid"]), "1981")
        self.assertEqual(user["name"], "calendar-mcp")
        self.assertEqual(user["group"], "calendar-mcp")
        self.assertTrue(user["system"])
        self.assertEqual(resolved(user["uid"]), "1980")
        self.assertEqual(user["shell"], "/usr/sbin/nologin")
        self.assertFalse(user["create_home"])

    def test_containers_run_as_the_registered_account(self):
        services = yaml.safe_load(
            render(
                "compose.yaml.j2",
                __calendar_mcp_image="calendar-mcp:x",
                **ACCOUNT_IDS,
            )
        )["services"]
        for name, service in services.items():
            with self.subTest(service=name):
                self.assertEqual(service.get("user"), "1980:1981")

    def test_account_owns_the_settings_and_data(self):
        for file, name, module in (
            ("config.yml", "config | Deploy settings", "ansible.builtin.template"),
            (
                "container.yml",
                "container | Create data directories",
                "ansible.builtin.file",
            ),
            ("container.yml", "container | Own data files", "ansible.builtin.file"),
        ):
            with self.subTest(task=name):
                args = task_named(file, name)[module]
                self.assertEqual(resolved(args["owner"]), "1980")
                self.assertEqual(resolved(args["group"]), "1981")

    def test_data_files_change_owner_before_the_containers_start(self):
        names = [
            task["name"]
            for task in yaml.safe_load((ROLE / "tasks" / "container.yml").read_text())
        ]
        self.assertLess(
            names.index("container | Own data files"),
            names.index("container | Start containers"),
        )
        own = task_named("container.yml", "container | Own data files")
        self.assertTrue(own["ansible.builtin.file"]["recurse"])
        self.assertNotIn("mode", own["ansible.builtin.file"])

    def test_data_walk_follows_no_link_and_runs_only_after_a_change(self):
        # The walk runs as root over a directory the container writes, so a
        # followed link would chown the host path it points at. In steady state
        # the directories are unchanged and root does not walk them at all.
        directories = task_named("container.yml", "container | Create data directories")
        own = task_named("container.yml", "container | Own data files")
        self.assertIs(own["ansible.builtin.file"]["follow"], False)
        self.assertEqual(directories["register"], "__calendar_mcp_data_dirs")
        self.assertEqual(own["loop"], "{{ __calendar_mcp_data_dirs.results }}")
        self.assertEqual(own["when"], "item is changed")
        self.assertEqual(
            render_expression(
                own["ansible.builtin.file"]["path"],
                **(role_vars() | {"item": {"item": {"name": "ts"}}}),
            ),
            "/srv/calendar_mcp/ts",
        )
        self.assertEqual(
            render_expression(
                directories["ansible.builtin.file"]["path"],
                **(role_vars() | {"item": {"name": "ts"}}),
            ),
            "/srv/calendar_mcp/ts",
        )


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

    def test_start_waits_for_health(self):
        task = task_named("container.yml", "container | Start containers")
        module = task["community.docker.docker_compose_v2"]
        self.assertIs(module["wait"], True)

    def test_health_check_needs_no_curl(self):
        # The upstream image declares a curl health check but ships no curl.
        for service in self.services().values():
            test = " ".join(service["healthcheck"]["test"])
            self.assertIn("/dev/tcp/127.0.0.1/8080", test)
            self.assertIn("GET /health", test)
            self.assertNotIn("curl", test)


NETWORKS = {
    "aws_private_ipv4": "10.0.0.0/16",
    "aws_public_ipv6": "2406:da14::/56",
    "home_private_ipv4": "192.168.0.0/24",
    "home_private_ipv6": "fd20::/64",
    "home_public_ipv4": "198.51.100.9/32",
    "home_public_ipv6": "2001:db8::/64",
    "office_public_ipv4": ["203.0.113.0/24"],
}
HOSTNAME = "calendar-mcp.rewse.jp"


def vhost() -> str:
    return render("calendar-mcp.rewse.jp.conf.j2", networks=NETWORKS)


def location_block(text: str, pattern: str) -> str:
    match = re.search(
        rf'<LocationMatch "{re.escape(pattern)}">(?P<body>.*?)</LocationMatch>',
        text,
        re.DOTALL,
    )
    assert match is not None, pattern
    return match["body"]


def denied_pattern(text: str) -> re.Pattern:
    match = re.search(
        r'<LocationMatch "(?P<pattern>[^"]+)">\s*Require all denied\s*</LocationMatch>',
        text,
    )
    assert match is not None
    return re.compile(match["pattern"])


def network_pattern(text: str) -> re.Pattern:
    match = re.search(
        r'<LocationMatch "(?P<pattern>[^"]+)">\s*Require ip ',
        text,
    )
    assert match is not None
    return re.compile(match["pattern"])


def access_line(host: str, request: str, status: int) -> str:
    # A vhost_combined line as fail2ban sees it, with the timestamp removed.
    return (
        f'{host}:443 203.0.113.7 - - [] "{request} HTTP/1.1" {status} 28 "-" "curl" 512'
    )


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


class CalendarMcpApacheTest(unittest.TestCase):
    def test_only_exact_user_paths_are_open(self):
        denied = denied_pattern(vhost())
        for path in ("/mcp/ts", "/mcp/ubiqu", "/health/ts", "/health/ubiqu"):
            with self.subTest(path=path):
                self.assertIsNone(denied.match(path))
        for path in (
            "/",
            "/mcp",
            "/mcp/ts/",
            "/mcp/ts/admin",
            "/mcp/ts/admin/ui",
            "/mcp/ts/attachments",
            "/mcp/ts/sse",
            "/mcp/tsx",
            "/mcp/kyn",
            "/admin",
            "/health",
            "/health/ts/ready",
        ):
            with self.subTest(path=path):
                self.assertIsNotNone(denied.match(path))

    def test_each_path_reaches_its_own_port(self):
        lines = [line.strip() for line in vhost().splitlines()]
        for expected in (
            "ServerName calendar-mcp.rewse.jp",
            "ProxyPreserveHost on",
            # ProxyPass rather than ProxyPassMatch, which appends the whole
            # request path to a target without a backreference.
            "ProxyPass /mcp/ts http://127.0.0.1:8084/ flushpackets=on",
            "ProxyPass /mcp/ubiqu http://127.0.0.1:8085/ flushpackets=on",
            "ProxyPass /health/ts http://127.0.0.1:8084/health",
            "ProxyPass /health/ubiqu http://127.0.0.1:8085/health",
            "SSLCertificateFile /etc/letsencrypt/live/rewse.jp/fullchain.pem",
        ):
            with self.subTest(line=expected):
                self.assertIn(expected, lines)

    def test_network_rule_reopens_no_denied_path(self):
        # The network rule follows the deny rule, and Apache lets the later
        # section's Require replace the earlier one, so a path both match would
        # be open to the listed networks.
        allowed = network_pattern(vhost())
        for path in ("/health/ts", "/health/ubiqu"):
            with self.subTest(path=path):
                self.assertIsNotNone(allowed.match(path))
        for path in (
            "/health/",
            "/health/ts/",
            "/health/ts/ready",
            "/health/tsx",
            "/health/kyn",
        ):
            with self.subTest(path=path):
                self.assertIsNone(allowed.match(path))

    def test_health_is_limited_to_known_networks(self):
        block = location_block(vhost(), network_pattern(vhost()).pattern)
        self.assertIn("Require ip 192.168.0.0/24", block)
        self.assertIn("Require ip 203.0.113.0/24", block)
        self.assertNotIn("Require all granted", block)

    def test_components_are_imported_in_order(self):
        imports = [
            task["ansible.builtin.import_tasks"]
            for task in yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
        ]
        self.assertEqual(
            imports,
            [
                "user.yml",
                "config.yml",
                "container.yml",
                "apache.yml",
                "fail2ban.yml",
            ],
        )


class CalendarMcpFail2banTest(unittest.TestCase):
    def test_filter_matches_rejected_mcp_calls(self):
        for request in ("POST /mcp/ts", "GET /mcp/ubiqu", "POST /mcp/ts?x=1"):
            with self.subTest(request=request):
                self.assertTrue(matches(access_line(HOSTNAME, request, 401)))

    def test_filter_ignores_metadata_success_and_other_vhosts(self):
        for line in (
            access_line(HOSTNAME, "GET /.well-known/oauth-protected-resource", 401),
            access_line(HOSTNAME, "POST /mcp/ts", 200),
            access_line(HOSTNAME, "GET /health/ts", 200),
            access_line("zabbix-mcp.rewse.jp", "POST /mcp/ts", 401),
        ):
            with self.subTest(line=line):
                self.assertFalse(matches(line))

    def test_jail_reads_the_apache_log(self):
        parser = configparser.ConfigParser(interpolation=None)
        parser.read_string(
            "\n".join(
                line
                for line in render("fail2ban-jail.conf.j2").splitlines()
                if not line.lstrip().startswith("#")
            )
        )
        jail = parser["calendar_mcp"]
        self.assertEqual(jail["filter"], "calendar_mcp")
        self.assertEqual(jail["backend"], "auto")
        self.assertEqual(jail["logpath"], "/var/log/apache2/other_vhosts_access.log")


if __name__ == "__main__":
    unittest.main()
