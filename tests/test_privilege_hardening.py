#!/usr/bin/env python3
"""Regression tests for services that grant remote access to root or secrets."""

import configparser
import json
import pathlib
import re
import subprocess
import unittest

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


class EnecoqDataFetcherCredentialsTest(unittest.TestCase):
    # Any local user can read a process's command line, so the enecoQ
    # credentials reach the fetcher through its environment, set in a script
    # that only root can read.
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
        self.assertEqual(task["mode"], "0700")


class SecretOutputTest(unittest.TestCase):
    # Under --diff or -v these print the secret they write, into the terminal
    # and into the transcript of an agent that runs the playbook.
    TASKS = (
        ("couchdb", "handlers/main.yml", "Run couchdb init script"),
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
