#!/usr/bin/env python3
"""Regression tests for services that grant remote access to root or secrets."""

import base64
import configparser
import http.server
import json
import os
import pathlib
import re
import subprocess
import tempfile
import textwrap
import threading
import unittest

import jinja2
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
RSYNCD_CONF = (
    REPO_ROOT / "roles" / "homeassistant_ha_primary" / "templates" / "rsyncd.conf.j2"
)
COUCHDB = REPO_ROOT / "roles" / "couchdb"
HOMEASSISTANT = REPO_ROOT / "roles" / "homeassistant"
PRIMARY = REPO_ROOT / "roles" / "homeassistant_ha_primary"
SECONDARY = REPO_ROOT / "roles" / "homeassistant_ha_secondary"
ZABBIX_FILES = REPO_ROOT / "roles" / "zabbix_agent" / "files"
MONEY_MARKET = REPO_ROOT / "roles" / "zabbix_money_market"
ADMIN_CONF = REPO_ROOT / "roles" / "httpd" / "templates" / "admin.conf.j2"
ZABBIX_ACCESS_CONF = (
    REPO_ROOT / "roles" / "zabbix_server" / "templates" / "zabbix-api.conf.j2"
)


def tracked_files(directory: pathlib.Path) -> list[pathlib.Path]:
    # Ignored files such as Finder's binary .DS_Store are never deployed, and
    # reading them as text fails.
    listing = subprocess.run(
        ["git", "ls-files", "-z", "--", str(directory)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [REPO_ROOT / name for name in sorted(listing.split("\0")) if name]


# The Zabbix script "Restart bluetooth" runs this command on the agent.
RESTART_BLUETOOTH = "sudo systemctl daemon-reload; sudo systemctl restart bluetooth"


class CouchDBSecurityAgentTest(unittest.TestCase):
    # The AWS Security Agent pentest signs in to CouchDB as a user that may read
    # one decoy database and write nothing, so a probe cannot alter or read the
    # Obsidian LiveSync databases.
    def validate(self, roles: list[str]) -> bool:
        design = json.loads(
            (COUCHDB / "files" / "security-agent-readonly.json").read_text()
        )
        script = (
            f"const validate = {design['validate_doc_update']};"
            "try { validate({}, null, JSON.parse(process.argv[1])); }"
            " catch (e) { process.exit(e.forbidden ? 3 : 1); }"
        )
        result = subprocess.run(
            ["node", "-e", script, json.dumps({"name": "x", "roles": roles})],
            check=False,
        )
        self.assertIn(result.returncode, (0, 3))
        return result.returncode == 0

    def test_design_document_rejects_writes_by_members(self):
        self.assertFalse(self.validate([]))

    def test_design_document_lets_admins_write(self):
        self.assertTrue(self.validate(["_admin"]))

    def test_only_the_pentest_user_is_a_member(self):
        variables = yaml.safe_load((COUCHDB / "vars" / "main.yml").read_text())
        security = variables["couchdb_security_agent_security"]
        self.assertEqual(
            security,
            {
                "admins": {"names": [], "roles": []},
                "members": {
                    "names": ["{{ couchdb_security_agent_user }}"],
                    "roles": [],
                },
            },
        )
        self.assertEqual(variables["couchdb_security_agent_user"], "security-agent")
        self.assertRegex(
            variables["couchdb_security_agent_password"],
            r"^\{\{ lookup\('pipe', 'op read op://ansible/\w+/password'\) \}\}$",
        )


class StandbySyncTest(unittest.TestCase):
    # The pulls carry secrets.yaml and the certificate's private key, so they
    # run over the standby's authenticated, encrypted SSH login to the primary
    # rather than over an rsync daemon.
    PULLS = (
        SECONDARY / "templates" / "homeassistant-sync.j2",
        SECONDARY / "templates" / "sslcert-sync.j2",
        SECONDARY / "templates" / "homeassistant-failback.j2",
    )

    def test_standby_pulls_over_ssh(self):
        for script in self.PULLS:
            with self.subTest(script=script.name):
                text = script.read_text()
                self.assertNotIn("rsync://", text)
                self.assertIn('--rsync-path="sudo rsync"', text)
                self.assertIn("-o BatchMode=yes", text)
                self.assertIn("[% admin_user %]", text)

    def test_standby_installs_pull_scripts_from_templates(self):
        tasks = {
            **template_tasks(SECONDARY / "tasks" / "rsync.yml"),
            **template_tasks(SECONDARY / "tasks" / "sslcert.yml"),
        }
        for name in ("homeassistant-sync", "sslcert-sync"):
            with self.subTest(name=name):
                task = tasks[f"/usr/local/bin/{name}"]
                self.assertEqual(task["variable_start_string"], "[%")
                self.assertFalse((SECONDARY / "files" / name).exists())

    def test_primary_runs_no_rsync_daemon(self):
        self.assertFalse(RSYNCD_CONF.exists())
        tasks = yaml.safe_load((PRIMARY / "tasks" / "rsync.yml").read_text())
        service = next(
            t["ansible.builtin.systemd"]
            for t in tasks
            if "ansible.builtin.systemd" in t
        )
        self.assertEqual(service["name"], "rsync")
        self.assertEqual(service["state"], "stopped")
        self.assertFalse(service["enabled"])
        removed = {
            t["ansible.builtin.file"]["path"]
            for t in tasks
            if t.get("ansible.builtin.file", {}).get("state") == "absent"
        }
        self.assertEqual(removed, {"/etc/logrotate.d/rsyncd", "/etc/rsyncd.conf"})
        self.assertNotIn(
            "homeassistant.rsync.active",
            (PRIMARY / "templates" / "homeassistant-ha.conf.j2").read_text(),
        )


class StandbyProbeTest(unittest.TestCase):
    # The standby asks the primary's Home Assistant whether it is up over plain
    # HTTP on the LAN, so the probe has to carry no credential: a token there
    # would cross the network in clear text and show up in the process list.
    # Unauthenticated, /api/ answers 401 and counts towards an IP ban, while
    # /manifest.json is public and served once the HTTP server is listening.
    SCRIPTS = (
        SECONDARY / "templates" / "homeassistant-failback.j2",
        SECONDARY / "templates" / "homeassistant-failover.j2",
    )

    def test_probe_sends_no_credential(self):
        for script in self.SCRIPTS:
            with self.subTest(script=script.name):
                text = script.read_text()
                self.assertNotRegex(text, r"(?i)authorization|bearer|token")
                self.assertNotIn("/api/", text)

    def test_probe_expects_the_public_manifest(self):
        for script in self.SCRIPTS:
            with self.subTest(script=script.name):
                text = script.read_text()
                self.assertIn(
                    'PRIMARY_PROBE="http://${PRIMARY_HOST}:8123/manifest.json"',
                    text,
                )
                self.assertRegex(text, r"\n\s+200\)\n")
                self.assertNotRegex(text, r"2\?\?|3\?\?")

    def test_standby_defines_no_token(self):
        for path in tracked_files(SECONDARY):
            with self.subTest(path=path.relative_to(SECONDARY).as_posix()):
                self.assertNotIn("_token", path.read_text())


class ZabbixAgentTest(unittest.TestCase):
    def test_bluetooth_agent_allows_only_restart_command(self):
        keys = [
            line
            for line in (ZABBIX_FILES / "bluetooth-devices.conf")
            .read_text()
            .splitlines()
            if re.match(r"(Allow|Deny)Key=", line)
        ]
        self.assertEqual(
            keys,
            [
                f"AllowKey=system.run[{RESTART_BLUETOOTH}]",
                f"AllowKey=system.run[{RESTART_BLUETOOTH},*]",
                "DenyKey=system.run[*]",
            ],
        )

    def key_rules(self) -> list[str]:
        return [
            line
            for line in (ZABBIX_FILES / "deny-file-keys.conf").read_text().splitlines()
            if re.match(r"(Allow|Deny)Key=", line)
        ]

    def copied_sources(self, task_file: str) -> list[str]:
        tasks = yaml.safe_load((ZABBIX_FILES.parent / "tasks" / task_file).read_text())
        return [task.get("ansible.builtin.copy", {}).get("src") for task in tasks]

    def test_agent_denies_keys_that_read_files(self):
        # These keys return the contents, matching lines, or listing of any file
        # the agent's account can open to whoever can query the agent.
        denied = [
            rule.removeprefix("DenyKey=")
            for rule in self.key_rules()
            if rule.startswith("DenyKey=")
        ]
        self.assertEqual(
            denied,
            [
                "log.count[*]",
                "log[*]",
                "logrt.count[*]",
                "logrt[*]",
                "vfs.dir.get[*]",
                "vfs.file.contents[*]",
                "vfs.file.get[*]",
                "vfs.file.regexp[*]",
                "vfs.file.regmatch[*]",
            ],
        )

    def test_agent_allows_only_the_log_items_in_use(self):
        # The agent applies the first rule a key matches, so each allowed key
        # must come before the denials and name its log file literally.
        rules = self.key_rules()
        allowed = [
            rule.removeprefix("AllowKey=")
            for rule in rules
            if rule.startswith("AllowKey=")
        ]
        self.assertEqual(
            allowed,
            [
                (
                    'log.count[/var/log/syslog,"nvme.*(controller is down|Unable to'
                    ' change power state)",UTF-8,,skip]'
                ),
                "log[/var/log/remote.log,,UTF-8]",
                "log[/var/log/syslog,,UTF-8]",
            ],
        )
        first_deny = next(
            index for index, rule in enumerate(rules) if rule.startswith("DenyKey=")
        )
        self.assertTrue(
            all(rule.startswith("AllowKey=") for rule in rules[:first_deny])
        )
        self.assertFalse(
            any(rule.startswith("AllowKey=") for rule in rules[first_deny:])
        )
        for key in allowed:
            with self.subTest(key=key):
                path = key.split("[", 1)[1].split(",", 1)[0]
                self.assertRegex(path, r"^/var/log/[a-z.]+$")

    def test_every_platform_copies_the_key_restrictions(self):
        self.assertIn("deny-file-keys.conf", self.copied_sources("config.yml"))
        for platform in ("ec2.yml", "raspberrypi.yml"):
            with self.subTest(platform=platform):
                self.assertNotIn("deny-file-keys.conf", self.copied_sources(platform))

    def test_zabbix_account_joins_adm_only_where_the_agent_needs_it(self):
        # Other services also run as zabbix, and adm opens Apache, auth, and
        # system logs. The Raspberry Pi agent runs as root; the unprivileged
        # agent on EC2 needs adm for its syslog item.
        defaults = yaml.safe_load(
            (ZABBIX_FILES.parent / "defaults" / "main.yml").read_text()
        )
        self.assertEqual(defaults["zabbix_agent_groups"], [])
        tasks = yaml.safe_load(
            (ZABBIX_FILES.parent / "tasks" / "package.yml").read_text()
        )
        users = [
            task["ansible.builtin.user"]
            for task in tasks
            if task.get("ansible.builtin.user", {}).get("name") == "zabbix"
        ]
        self.assertEqual(
            users,
            [
                {
                    "name": "zabbix",
                    "groups": "{{ zabbix_agent_groups }}",
                    "append": False,
                }
            ],
        )
        for path in sorted(
            (REPO_ROOT / "inventory" / "host_vars").glob("*/zabbix_agent.yml")
        ):
            host_vars = yaml.safe_load(path.read_text())
            with self.subTest(host=path.parent.name):
                if host_vars["zabbix_agent_platform"] == "raspberrypi":
                    self.assertEqual(host_vars.get("zabbix_agent_groups", []), [])
                else:
                    self.assertLessEqual(
                        set(host_vars.get("zabbix_agent_groups", [])), {"adm"}
                    )

    def test_agent_keeps_file_metadata_keys(self):
        # The OS templates monitor checksums and existence of system files.
        rules = "\n".join(self.key_rules())
        self.assertNotIn("vfs.file[", rules)
        self.assertNotIn("vfs.file.*", rules)
        for key in ("cksum", "exists", "size", "time"):
            with self.subTest(key=key):
                self.assertNotIn(f"vfs.file.{key}", rules)

    def test_zabbix_sudo_grants_only_listed_commands(self):
        rules = [
            line
            for line in (ZABBIX_FILES / "zabbix.sudo").read_text().splitlines()
            if line.strip() and not line.startswith("#")
        ]
        self.assertTrue(rules)
        for rule in rules:
            self.assertNotRegex(rule, r"NOPASSWD:\s*ALL\b")
        commands = " ".join(rules)
        self.assertIn("/usr/bin/systemctl restart bluetooth", commands)
        self.assertIn("/usr/bin/systemctl daemon-reload", commands)
        self.assertIn(
            "/usr/bin/docker inspect --format {{.State.Running}} homeassistant",
            commands,
        )
        self.assertIn(
            "/usr/bin/docker inspect --format {{.Config.Image}} homeassistant",
            commands,
        )


class ZabbixFrontendTest(unittest.TestCase):
    def test_frontend_is_limited_to_home_and_office(self):
        text = ZABBIX_ACCESS_CONF.read_text()
        frontend = text.index('<Location "/zabbix">')
        api = text.index('<Location "/zabbix/api_jsonrpc.php">')
        # Apache applies Location sections in order, so the narrower API block
        # must come after the frontend block to override it.
        self.assertLess(frontend, api)
        block = text[frontend : text.index("</Location>", frontend)]
        for network in (
            "networks.home_private_ipv4",
            "networks.home_public_ipv4",
            "networks.home_public_ipv6",
            "networks.home_private_ipv6",
            "networks.office_public_ipv4 | join(' ')",
        ):
            with self.subTest(network=network):
                self.assertIn(network, block)


class AdminPagesTest(unittest.TestCase):
    def test_admin_pages_are_limited_by_url_path(self):
        # Apache serves /var/www/html through the /var/www -> /srv/www symlink
        # and matches <Directory> against the unresolved path, so a
        # <Directory /srv/www/...> block never applies to these pages.
        text = ADMIN_CONF.read_text()
        self.assertIn('<Location "/admin">', text)
        self.assertNotRegex(text, r"(?m)^<Directory")
        self.assertIn("Require ip", text)


class HomeAssistantAgentConfigTest(unittest.TestCase):
    # The agent runs as root on the primary, so root alone needs to read the
    # Home Assistant API token, and it stays off curl's command line.
    CURLRC = "/etc/zabbix/homeassistant-ha.curlrc"

    def test_agent_config_holds_no_token(self):
        text = (PRIMARY / "templates" / "homeassistant-ha.conf.j2").read_text()
        self.assertNotIn("homeassistant_ha_primary_token", text)
        self.assertNotIn("Authorization", text)
        self.assertRegex(
            text,
            r"(?m)^UserParameter=homeassistant\.api\.http_code,curl -s "
            rf"-K {re.escape(self.CURLRC)} ",
        )

    def test_token_file_is_private(self):
        task = template_tasks(PRIMARY / "tasks" / "zabbix.yml")[self.CURLRC]
        self.assertEqual(task["src"], "homeassistant-ha.curlrc.j2")
        self.assertEqual(task["mode"], "0600")
        self.assertEqual(task["owner"], "root")
        self.assertEqual(task["group"], "root")
        text = (PRIMARY / "templates" / task["src"]).read_text()
        self.assertIn(
            'header = "Authorization: Bearer {{ homeassistant_ha_primary_token }}"',
            text.splitlines(),
        )


class StockPriceFetcherCheckoutTest(unittest.TestCase):
    # root runs git in this checkout, and git executes .git/config and hooks, so
    # zabbix, which runs a browser on scraped pages, must not be able to write it.
    CHECKOUT = "/opt/stock-price-fetcher"

    def tasks(self) -> list[dict]:
        return yaml.safe_load((MONEY_MARKET / "tasks" / "app.yml").read_text())

    def test_checkout_stays_root_owned(self):
        handlers = (MONEY_MARKET / "handlers" / "main.yml").read_text()
        self.assertNotIn(self.CHECKOUT, handlers)
        for task in self.tasks():
            with self.subTest(task=task["name"]):
                spec = task.get("ansible.builtin.file", {})
                if spec.get("path") == self.CHECKOUT:
                    self.assertEqual(spec.get("owner"), "root")
                    self.assertEqual(spec.get("group"), "root")
                git = task.get("ansible.builtin.git")
                if git:
                    self.assertNotIn("become_user", task)
                    self.assertNotIn("notify", task)

    def test_root_does_not_trust_a_foreign_checkout(self):
        for task in self.tasks():
            with self.subTest(task=task["name"]):
                spec = task.get("community.general.git_config", {})
                self.assertNotEqual(spec.get("name"), "safe.directory")

    def test_environment_lives_outside_the_checkout(self):
        venv = yaml.safe_load((MONEY_MARKET / "vars" / "main.yml").read_text())[
            "zabbix_money_market_venv"
        ]
        self.assertFalse(venv.startswith(self.CHECKOUT + "/"))
        sync = next(
            t
            for t in self.tasks()
            if "uv sync" in str(t.get("ansible.builtin.command"))
        )
        self.assertEqual(sync["become_user"], "zabbix")
        self.assertEqual(
            sync["environment"],
            {"UV_PROJECT_ENVIRONMENT": "{{ zabbix_money_market_venv }}"},
        )
        send = (MONEY_MARKET / "templates" / "stock-price-fetcher-send.j2").read_text()
        self.assertIn(
            'export UV_PROJECT_ENVIRONMENT="{{ zabbix_money_market_venv }}"', send
        )
        self.assertLess(
            send.index("export UV_PROJECT_ENVIRONMENT"), send.index("uv run")
        )


def template_tasks(path: pathlib.Path) -> dict[str, dict]:
    return {
        t["ansible.builtin.template"]["dest"]: t["ansible.builtin.template"]
        for t in yaml.safe_load(path.read_text())
        if "ansible.builtin.template" in t
    }


class HomeAssistantSecretFilesTest(unittest.TestCase):
    # Home Assistant runs as root in its container, and the standby's sync reads
    # them through sudo on the primary, so root alone needs to read these.
    def test_secret_config_is_private(self):
        tasks = template_tasks(HOMEASSISTANT / "tasks" / "configuration.yml")
        for name in ("secrets.yaml", "shell_commands.yaml"):
            with self.subTest(name=name):
                task = tasks[f"/srv/homeassistant/config/{name}"]
                self.assertEqual(task["mode"], "0600")
                self.assertEqual(task["owner"], "root")
                self.assertEqual(task["group"], "root")

    def test_failover_scripts_are_private(self):
        tasks = template_tasks(SECONDARY / "tasks" / "failover.yml")
        for name in (
            "homeassistant-failback",
            "homeassistant-failover",
            "homeassistant-name-switch",
        ):
            with self.subTest(name=name):
                task = tasks[f"/usr/local/bin/{name}"]
                self.assertEqual(task["mode"], "0700")
                self.assertEqual(task["owner"], "root")
                self.assertEqual(task["group"], "root")


class CommandLineSecretsTest(unittest.TestCase):
    # Any local user can read a process's command line from /proc, so
    # credentials reach curl through stdin or a root-only file instead.
    API_KEY = "test-api-key"

    @staticmethod
    def write_executable(path: pathlib.Path, content: str) -> None:
        path.write_text(content)
        path.chmod(0o755)

    def test_unifi_api_key_reaches_curl_on_stdin(self):
        root = pathlib.Path(self.enterContext(tempfile.TemporaryDirectory()))
        environment = jinja2.Environment(
            loader=jinja2.FileSystemLoader(SECONDARY / "templates"),
            undefined=jinja2.StrictUndefined,
            variable_start_string="[%",
            variable_end_string="%]",
        )
        environment.filters["comment"] = lambda text: f"#\n# {text}\n#"
        script = environment.get_template("homeassistant-name-switch.j2").render(
            ansible_managed="Ansible managed",
            homeassistant_ha_secondary_domain="hass.example.com",
            homeassistant_ha_secondary_primary_ip="192.0.2.1",
            homeassistant_ha_secondary_standby_ip="192.0.2.2",
            homeassistant_ha_secondary_unifi_api_key=self.API_KEY,
            homeassistant_ha_secondary_unifi_console="console",
        )
        script = script.replace("/var/lib/homeassistant-ha", str(root / "state"))
        bin_dir = root / "bin"
        bin_dir.mkdir()
        # Records each argument on its own line and the headers read from
        # stdin, then answers as an account without consoles.
        self.write_executable(
            bin_dir / "curl",
            textwrap.dedent(
                f"""\
                #!/bin/sh
                printf '%s\\n' "$@" >> '{root}/argv'
                cat >> '{root}/stdin'
                echo '{{"data":[]}}'
                """
            ),
        )
        self.write_executable(bin_dir / "logger", "#!/bin/sh\nexit 0\n")
        self.write_executable(root / "name-switch", script)
        result = subprocess.run(
            [str(root / "name-switch"), "primary"],
            capture_output=True,
            check=False,
            env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"},
            stdin=subprocess.DEVNULL,
            text=True,
        )

        self.assertIn("No console named console", result.stdout)
        argv = (root / "argv").read_text()
        self.assertIn("https://api.ui.com/ea/hosts", argv)
        self.assertNotIn(self.API_KEY, argv)
        self.assertEqual((root / "stdin").read_text(), f"X-API-KEY: {self.API_KEY}\n")

    def test_regza_commands_read_credentials_from_netrc(self):
        text = (HOMEASSISTANT / "templates" / "shell_commands.yaml.j2").read_text()
        self.assertNotIn("homeassistant_regza", text)
        self.assertNotIn("--user", text)
        commands = yaml.safe_load(text.replace("[% ansible_managed | comment %]", ""))
        self.assertTrue(commands)
        for name, command in commands.items():
            with self.subTest(name=name):
                self.assertIn("--digest --netrc-file /config/regza.netrc", command)

    def test_regza_netrc_is_private(self):
        tasks = yaml.safe_load(
            (HOMEASSISTANT / "tasks" / "configuration.yml").read_text()
        )
        task = next(
            t
            for t in tasks
            if t.get("ansible.builtin.template", {}).get("dest")
            == "/srv/homeassistant/config/regza.netrc"
        )
        template = task["ansible.builtin.template"]
        # Home Assistant runs curl as root in its container.
        self.assertEqual(
            (template["owner"], template["group"], template["mode"]),
            ("root", "root", "0600"),
        )
        self.assertIs(task["no_log"], True)

    def test_regza_netrc_is_read_by_curl(self):
        username = 'remote "user"'
        password = 'p\\a"s s#'
        environment = jinja2.Environment(
            loader=jinja2.FileSystemLoader(HOMEASSISTANT / "templates"),
            undefined=jinja2.StrictUndefined,
        )
        environment.filters["comment"] = lambda text: f"#\n# {text}\n#"
        netrc = pathlib.Path(self.enterContext(tempfile.TemporaryDirectory()))
        netrc /= "regza.netrc"
        netrc.write_text(
            environment.get_template("regza.netrc.j2").render(
                ansible_managed="Ansible managed",
                homeassistant_regza={"password": password, "username": username},
            )
        )
        received: list[str] = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # name required by BaseHTTPRequestHandler
                received.append(self.headers.get("Authorization", ""))
                self.send_response(204)
                self.end_headers()

            def log_message(self, *args):  # pyright: ignore[reportIncompatibleMethodOverride]  # silences the request log
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.addCleanup(server.server_close)
        thread = threading.Thread(target=server.handle_request)
        thread.start()
        port = server.server_address[1]
        subprocess.run(
            [
                "curl",
                "--silent",
                "--netrc-file",
                str(netrc),
                "--resolve",
                f"regza.rewse.jp:{port}:127.0.0.1",
                f"http://regza.rewse.jp:{port}/",
            ],
            check=True,
            timeout=30,
        )
        thread.join(timeout=30)

        credentials = f"{username}:{password}".encode()
        self.assertEqual(received, ["Basic " + base64.b64encode(credentials).decode()])


class EnecoqDataFetcherCredentialsTest(unittest.TestCase):
    # Any local user can read a process's command line, so the enecoQ
    # credentials reach the fetcher through its environment, set in a script
    # that only root and the fetcher's own user can read.
    ROLE = REPO_ROOT / "roles" / "enecoq_data_fetcher"
    SCRIPT = "/usr/local/sbin/enecoq-data-fetcher"

    def test_credentials_stay_off_the_command_line(self):
        text = (self.ROLE / "templates" / "enecoq-data-fetcher.j2").read_text()
        self.assertNotIn("--email", text)
        self.assertNotIn("--password", text)

    def test_credentials_are_exported_shell_quoted(self):
        text = (self.ROLE / "templates" / "enecoq-data-fetcher.j2").read_text()
        for name, field in (
            ("ENECOQ_EMAIL", "email"),
            ("ENECOQ_PASSWORD", "password"),
        ):
            with self.subTest(name=name):
                self.assertIn(
                    f"{name}=[% enecoq_data_fetcher_enecoq.{field} | quote %]",
                    text.splitlines(),
                )
        self.assertIn("export ENECOQ_EMAIL ENECOQ_PASSWORD", text.splitlines())

    def test_script_is_private(self):
        task = template_tasks(self.ROLE / "tasks" / "service.yml")[self.SCRIPT]
        self.assertEqual(task["owner"], "root")
        self.assertEqual(task["group"], "{{ enecoq_data_fetcher_user }}")
        self.assertEqual(task["mode"], "0750")


class SecretOutputTest(unittest.TestCase):
    # Under --diff or -v these print the secret they write, into the terminal
    # and into the transcript of an agent that runs the playbook.
    TASKS = (
        ("couchdb", "handlers/main.yml", "Run couchdb init script"),
        ("enecoq_data_fetcher", "tasks/service.yml", "service | Install script"),
        ("homeassistant_ha_primary", "tasks/zabbix.yml", "zabbix | Copy curl config"),
        ("zabbix_mcp", "tasks/service.yml", "service | Deploy config"),
        ("zabbix_server", "tasks/frontend.yml", "frontend | Copy PHP config"),
        ("zabbix_server", "tasks/server.yml", "server | Set DBPassword"),
    )

    def test_secret_tasks_set_no_log(self):
        for role, path, name in self.TASKS:
            with self.subTest(role=role, name=name):
                tasks = yaml.safe_load((REPO_ROOT / "roles" / role / path).read_text())
                task = next(t for t in tasks if t["name"] == name)
                self.assertIs(task.get("no_log"), True)


class AnsibleConfigTest(unittest.TestCase):
    def test_host_keys_are_checked(self):
        # The playbooks push secrets, so a host that answers under a wrong or
        # spoofed name must stop the run instead of receiving them.
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(REPO_ROOT / "ansible.cfg")
        self.assertTrue(
            parser.getboolean("defaults", "host_key_checking", fallback=True)
        )

    def test_remote_tmp_is_private_to_the_remote_user(self):
        # Any local user can create a directory under /tmp before Ansible does,
        # for example after a reboot empties it, and then read or swap the
        # files Ansible stages there. The home directory is the user's own.
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(REPO_ROOT / "ansible.cfg")
        remote_tmp = parser.get("defaults", "remote_tmp", fallback="~/.ansible/tmp")
        self.assertTrue(remote_tmp.startswith("~/"), remote_tmp)


def walk_tasks(tasks: list[dict]):
    for task in tasks:
        yield task
        for key in ("block", "rescue", "always"):
            yield from walk_tasks(task.get(key, []))


class SharedTempDirectoryTest(unittest.TestCase):
    # For the same reason as remote_tmp, a task must not name a fixed path in
    # a directory every local user can write: another account can create the
    # path first, and a download without force keeps that file for root to
    # run or install.
    SHARED = re.compile(r"(?<![\w.~-])/(?:private/)?(?:var/)?tmp/")

    def test_tasks_name_no_path_in_shared_temp_directories(self):
        for path, tasks in task_lists():
            for task in walk_tasks(tasks):
                body = {k: v for k, v in task.items() if k != "name"}
                with self.subTest(file=str(path), task=task.get("name")):
                    self.assertIsNone(
                        self.SHARED.search(yaml.safe_dump(body, width=1000))
                    )


class StagedInstallerTest(unittest.TestCase):
    # Installers that root runs are downloaded into a fresh directory that
    # only root can write, replacing any file there, and the directory is
    # removed after the install.
    CASES = (
        ("nix", "nix.yml", "nix | Download installer", "nix | Install"),
        (
            "power_monitor",
            "app.yml",
            "app | Download package",
            "app | Install package",
        ),
    )

    def test_installers_are_staged_in_a_root_directory(self):
        for role, file, download_name, install_name in self.CASES:
            with self.subTest(role=role):
                tasks = yaml.safe_load(
                    (REPO_ROOT / "roles" / role / "tasks" / file).read_text()
                )
                names = [t["name"] for t in tasks]
                by_name = {t["name"]: t for t in tasks}
                staging = next(t for t in tasks if "ansible.builtin.tempfile" in t)
                self.assertEqual(
                    staging["ansible.builtin.tempfile"]["state"], "directory"
                )
                self.assertIs(staging["become"], True)
                directory = "{{ " + staging["register"] + ".path }}"

                download = by_name[download_name]
                spec = download["ansible.builtin.get_url"]
                self.assertTrue(spec["dest"].startswith(directory + "/"))
                self.assertIs(spec["force"], True)
                self.assertIs(download["become"], True)

                install = by_name[install_name]
                self.assertIs(install["become"], True)
                self.assertIn(spec["dest"], yaml.safe_dump(install, width=1000))

                removal = next(
                    t
                    for t in tasks
                    if t.get("ansible.builtin.file", {}).get("state") == "absent"
                    and t["ansible.builtin.file"]["path"] == directory
                )
                self.assertIs(removal["become"], True)
                self.assertLess(
                    names.index(staging["name"]), names.index(download_name)
                )
                self.assertLess(names.index(download_name), names.index(install_name))
                self.assertLess(names.index(install_name), names.index(removal["name"]))


# Home and state directories of accounts that are less trusted than root. Their
# owners can replace any entry in them with a symlink, so a task that writes
# there as root would write wherever the link points.
USER_OWNED_DIRECTORIES = {
    "/home/muse": "muse",
    "/var/lib/zabbix": "zabbix",
}
FILE_MODULES = (
    "ansible.builtin.blockinfile",
    "ansible.builtin.copy",
    "ansible.builtin.file",
    "ansible.builtin.lineinfile",
    "ansible.builtin.template",
)


def role_variables() -> dict[str, str]:
    variables = {}
    for path in sorted((REPO_ROOT / "roles").glob("*/vars/*.yml")):
        for name, value in (yaml.safe_load(path.read_text()) or {}).items():
            if isinstance(value, str):
                variables[name] = value
    return variables


def task_lists() -> list[tuple[pathlib.Path, list[dict]]]:
    paths = sorted((REPO_ROOT / "roles").glob("*/tasks/*.yml"))
    paths += sorted((REPO_ROOT / "roles").glob("*/handlers/*.yml"))
    return [(path, yaml.safe_load(path.read_text()) or []) for path in paths]


class UserOwnedPathTest(unittest.TestCase):
    def owner_of(self, text: str, variables: dict[str, str]) -> str | None:
        for name, value in variables.items():
            if re.search(rf"\b{re.escape(name)}\b", text):
                text += " " + value
        for directory, user in USER_OWNED_DIRECTORIES.items():
            if re.search(rf"{re.escape(directory)}(/|\b)", text):
                return user
        return None

    def test_file_tasks_in_user_owned_directories_run_as_the_user(self):
        variables = role_variables()
        checked = 0
        for path, tasks in task_lists():
            for task in tasks:
                module = next((m for m in FILE_MODULES if m in task), None)
                if module is None:
                    continue
                spec = task[module]
                target = str(spec.get("path", spec.get("dest", "")))
                if "item" in target:
                    target += " " + json.dumps(task.get("loop", ""))
                user = self.owner_of(target, variables)
                if user is None:
                    continue
                checked += 1
                with self.subTest(file=str(path), task=task["name"]):
                    self.assertEqual(task.get("become_user"), user)
        self.assertGreater(checked, 0)

    def test_authorized_keys_are_written_as_their_user(self):
        for path, tasks in task_lists():
            for task in tasks:
                spec = task.get("ansible.posix.authorized_key")
                if (
                    spec is None
                    or spec.get("user") not in USER_OWNED_DIRECTORIES.values()
                ):
                    continue
                with self.subTest(file=str(path), task=task["name"]):
                    self.assertEqual(task.get("become_user"), spec["user"])


# Service data that holds credentials, signing secrets, and device keys. Only
# root and the containers that bind-mount them use these trees, and a container
# reaches its mount without traversing the host path.
PRIVATE_DATA_DIRECTORIES = ("/srv/couchdb", "/srv/homeassistant/config", "/srv/nvr")
HOME_ASSISTANT_CONFIG = "/srv/homeassistant/config"


def file_task_paths(task: dict) -> list[str]:
    spec = task["ansible.builtin.file"]
    path = str(spec.get("path", ""))
    if "{{ item }}" in path:
        return [path.replace("{{ item }}", str(item)) for item in task.get("loop", [])]
    return [path]


class PrivateDataDirectoryTest(unittest.TestCase):
    def test_data_directories_are_private_to_root(self):
        seen = set()
        for path, tasks in task_lists():
            for task in tasks:
                if "ansible.builtin.file" not in task:
                    continue
                spec = task["ansible.builtin.file"]
                for target in file_task_paths(task):
                    if target not in PRIVATE_DATA_DIRECTORIES:
                        continue
                    seen.add(target)
                    with self.subTest(file=str(path), task=task["name"]):
                        self.assertEqual(spec["state"], "directory")
                        self.assertEqual(spec["mode"], "0700")
                        self.assertEqual(spec["owner"], "root")
                        self.assertEqual(spec["group"], "root")
        self.assertEqual(seen, set(PRIVATE_DATA_DIRECTORIES))

    def test_couchdb_directory_is_locked_before_its_contents(self):
        tasks = yaml.safe_load((COUCHDB / "tasks" / "container.yml").read_text())
        paths = [
            target
            for task in tasks
            if "ansible.builtin.file" in task
            for target in file_task_paths(task)
        ]
        self.assertLess(paths.index("/srv/couchdb"), paths.index("/srv/couchdb/data"))

    def test_standby_sync_carries_the_directory_mode(self):
        # rsync --archive with a trailing slash applies the primary's mode to
        # the standby's copy of the directory.
        text = (SECONDARY / "templates" / "homeassistant-sync.j2").read_text()
        self.assertIn("--archive", text)
        self.assertIn(
            f'SOURCE="[% admin_user %]@fox.rewse.jp:{HOME_ASSISTANT_CONFIG}/"', text
        )


class HomeAssistantConfigLinkTest(unittest.TestCase):
    # Home Assistant runs as root in its container and can replace any entry
    # under /config with a link, so a root task that follows one would change
    # the host path it points to.
    def test_file_tasks_do_not_follow_links(self):
        checked = 0
        for path, tasks in task_lists():
            for task in tasks:
                if "ansible.builtin.file" not in task:
                    continue
                spec = task["ansible.builtin.file"]
                if spec.get("state") == "absent":
                    continue
                if not any(
                    t.startswith(HOME_ASSISTANT_CONFIG) for t in file_task_paths(task)
                ):
                    continue
                checked += 1
                with self.subTest(file=str(path), task=task["name"]):
                    self.assertIs(spec.get("follow"), False)
        self.assertGreater(checked, 0)


def home_assistant_service(role: pathlib.Path) -> dict:
    lines = [
        line
        for line in (role / "templates" / "compose.yaml.j2").read_text().splitlines()
        if not line.startswith("{{")
    ]
    text = re.sub(r"\{\{.*?\}\}", "image-ref", "\n".join(lines))
    return yaml.safe_load(text)["services"]["homeassistant"]


class HomeAssistantContainerTest(unittest.TestCase):
    # Home Assistant gets the host's network, D-Bus, and the Zigbee dongle, and
    # only the capabilities Bluetooth management needs beyond Docker's default
    # set, rather than every device and capability the host has.
    def test_container_is_not_privileged(self):
        for role in (HOMEASSISTANT, SECONDARY):
            with self.subTest(role=role.name):
                service = home_assistant_service(role)
                self.assertNotIn("privileged", service)
                self.assertEqual(service["cap_add"], ["NET_ADMIN", "NET_RAW"])
                self.assertEqual(service["network_mode"], "host")
                self.assertEqual(service["security_opt"], ["apparmor:unconfined"])
                self.assertIn("/run/dbus:/run/dbus:ro", service["volumes"])

    def test_primary_keeps_the_zigbee_dongle(self):
        service = home_assistant_service(HOMEASSISTANT)
        self.assertEqual(service["devices"], ["/dev/ttyUSB0:/dev/ttyUSB0"])
        self.assertIn("/dev/serial/by-id:/dev/serial/by-id", service["volumes"])


class DockerAppArmorTest(unittest.TestCase):
    # aa-disable on docker-default unloaded the profile from every container
    # running at the time. Home Assistant runs apparmor:unconfined, so nothing
    # needs it, and a run has to undo it on hosts that still carry it.
    SERVICE = "aa-disable-homeassistant"

    def test_workaround_is_gone(self):
        self.assertFalse((HOMEASSISTANT / "files" / f"{self.SERVICE}.service").exists())
        for path in (HOMEASSISTANT / "tasks").glob("*.yml"):
            with self.subTest(file=path.name):
                text = path.read_text()
                self.assertNotIn("files/9417617/docker-default", text)
        handlers = (HOMEASSISTANT / "handlers" / "main.yml").read_text()
        self.assertNotIn(self.SERVICE, handlers)
        compose = (HOMEASSISTANT / "templates" / "compose.yaml.j2").read_text()
        self.assertIn("apparmor:unconfined", compose)

    def test_run_removes_the_workaround_from_hosts(self):
        tasks = yaml.safe_load((HOMEASSISTANT / "tasks" / "apparmor.yml").read_text())
        service = next(
            t["ansible.builtin.systemd"]
            for t in tasks
            if t.get("ansible.builtin.systemd", {}).get("name") == self.SERVICE
        )
        self.assertIs(service["enabled"], False)
        self.assertEqual(service["state"], "stopped")
        removed = {
            t["ansible.builtin.file"]["path"]
            for t in tasks
            if t.get("ansible.builtin.file", {}).get("state") == "absent"
        }
        self.assertEqual(
            removed,
            {
                f"/etc/systemd/system/{self.SERVICE}.service",
                "/etc/apparmor.d/disable/docker-default",
                "/etc/apparmor.d/docker-default",
            },
        )


if __name__ == "__main__":
    unittest.main()
