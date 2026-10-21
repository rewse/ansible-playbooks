#!/usr/bin/env python3
"""Regression tests for services that grant remote access to root or secrets."""

import configparser
import pathlib
import re
import unittest

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
RSYNCD_CONF = (
    REPO_ROOT / "roles" / "homeassistant_ha_primary" / "templates" / "rsyncd.conf.j2"
)
HOMEASSISTANT = REPO_ROOT / "roles" / "homeassistant"
PRIMARY = REPO_ROOT / "roles" / "homeassistant_ha_primary"
SECONDARY = REPO_ROOT / "roles" / "homeassistant_ha_secondary"
ZABBIX_FILES = REPO_ROOT / "roles" / "zabbix_agent" / "files"
MONEY_MARKET = REPO_ROOT / "roles" / "zabbix_money_market"
ADMIN_CONF = REPO_ROOT / "roles" / "httpd" / "templates" / "admin.conf.j2"
ZABBIX_ACCESS_CONF = (
    REPO_ROOT / "roles" / "zabbix_server" / "templates" / "zabbix-api.conf.j2"
)

# The Zabbix script "Restart bluetooth" runs this command on the agent.
RESTART_BLUETOOTH = "sudo systemctl daemon-reload; sudo systemctl restart bluetooth"


def rsyncd_modules() -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    lines = [
        line.strip()
        for line in RSYNCD_CONF.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith(("#", "{{"))
    ]
    parser.read_string("[global]\n" + "\n".join(lines))
    return parser


class RsyncdTest(unittest.TestCase):
    def test_homeassistant_config_module_allows_only_standby(self):
        module = rsyncd_modules()["homeassistant-config"]
        self.assertEqual(
            module["hosts allow"], "{{ homeassistant_ha_primary_standby_ip }}"
        )
        self.assertEqual(module["hosts deny"], "*")

    def test_standby_pulls_homeassistant_config_over_ipv4(self):
        # The module allows only the standby's IPv4 address, and fox.rewse.jp
        # also resolves to IPv6, so every client must force IPv4.
        for script in (
            SECONDARY / "files" / "homeassistant-sync",
            SECONDARY / "templates" / "homeassistant-failback.j2",
        ):
            with self.subTest(script=script.name):
                self.assertIn("--ipv4", script.read_text())


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
    def test_token_bearing_agent_config_is_not_world_readable(self):
        # homeassistant-ha.conf carries the Home Assistant API token.
        tasks = yaml.safe_load((PRIMARY / "tasks" / "zabbix.yml").read_text())
        task = next(
            t["ansible.builtin.template"]
            for t in tasks
            if t.get("ansible.builtin.template", {}).get("src")
            == "homeassistant-ha.conf.j2"
        )
        self.assertEqual(task["mode"], "0640")
        self.assertEqual(task["owner"], "root")
        self.assertEqual(task["group"], "zabbix")


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
    # Home Assistant runs as root in its container, and rsyncd and the standby's
    # sync run as root, so root alone needs to read these.
    def test_secret_config_is_private(self):
        tasks = template_tasks(HOMEASSISTANT / "tasks" / "configuration.yml")
        for name in ("secrets.yaml", "shell_commands.yaml"):
            with self.subTest(name=name):
                task = tasks[f"/srv/homeassistant/config/{name}"]
                self.assertEqual(task["mode"], "0600")
                self.assertEqual(task["owner"], "root")
                self.assertEqual(task["group"], "root")

    def test_token_bearing_failover_scripts_are_private(self):
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


class SecretOutputTest(unittest.TestCase):
    # Under --diff or -v these print the secret they write, into the terminal
    # and into the transcript of an agent that runs the playbook.
    TASKS = (
        ("couchdb", "handlers/main.yml", "Run couchdb init script"),
        ("zabbix_mcp", "tasks/service.yml", "service | Deploy config"),
        ("zabbix_server", "tasks/frontend.yml", "frontend | Copy PHP config"),
        ("zabbix_server", "tasks/server.yml", "server | Set DBPassword"),
    )

    def test_secret_tasks_set_no_log(self):
        for role, path, name in self.TASKS:
            with self.subTest(role=role, name=name):
                tasks = yaml.safe_load(
                    (REPO_ROOT / "roles" / role / path).read_text()
                )
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


if __name__ == "__main__":
    unittest.main()
