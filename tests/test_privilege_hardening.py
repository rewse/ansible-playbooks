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
PRIMARY = REPO_ROOT / "roles" / "homeassistant_ha_primary"
SECONDARY = REPO_ROOT / "roles" / "homeassistant_ha_secondary"
ZABBIX_FILES = REPO_ROOT / "roles" / "zabbix_agent" / "files"
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


if __name__ == "__main__":
    unittest.main()
