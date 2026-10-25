#!/usr/bin/env python3
"""Contract tests for the zabbix_mcp role."""

import pathlib
import re
import tomllib
import unittest

import jinja2
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROLE = REPO_ROOT / "roles" / "zabbix_mcp"

NETWORKS = {
    "aws_private_ipv4": "10.0.0.0/16",
    "aws_public_ipv6": "2001:db8:aa::/56",
    "home_private_ipv4": "192.168.0.0/24",
    "home_private_ipv6": "fd00:db8::/64",
    "home_public_ipv4": "192.0.2.9/32",
    "home_public_ipv6": "2001:db8:bb::/64",
    "office_public_ipv4": ["198.51.100.0/24", "203.0.113.0/24"],
}


def role_vars() -> dict:
    return yaml.safe_load((ROLE / "vars" / "main.yml").read_text())


def render(name: str, **overrides) -> str:
    environment = jinja2.Environment(
        loader=jinja2.FileSystemLoader(ROLE / "templates"),
        undefined=jinja2.StrictUndefined,
    )
    environment.filters["comment"] = lambda text: f"#\n# {text}\n#"
    # Ansible returns a defined value unchanged, so a string literal passes.
    environment.filters["mandatory"] = lambda value: value
    environment.filters["regex_escape"] = re.escape
    variables = role_vars()
    hostname = variables["zabbix_mcp_hostname"]
    context = {
        "ansible_managed": "Ansible managed",
        "networks": NETWORKS,
        "zabbix_mcp_api_token": "api-token",
        "zabbix_mcp_auth_token": "auth-token",
        "zabbix_mcp_hostname": hostname,
        "zabbix_mcp_port": variables["zabbix_mcp_port"],
        "zabbix_mcp_public_url": f"https://{hostname}",
        "zabbix_mcp_read_only": False,
        "zabbix_mcp_url": "https://zabbix.example.com",
    }
    context.update(overrides)
    return environment.get_template(name).render(**context)


class ZabbixMcpServerTest(unittest.TestCase):
    def test_server_listens_on_loopback_only(self):
        server = tomllib.loads(render("config.toml.j2"))["server"]
        self.assertEqual(server["host"], "127.0.0.1")
        self.assertEqual(server["port"], 8081)

    def test_public_url_is_the_apache_vhost(self):
        variables = yaml.safe_load((ROLE / "vars" / "main.yml").read_text())
        self.assertEqual(variables["zabbix_mcp_hostname"], "zabbix-mcp.rewse.jp")
        self.assertEqual(
            variables["zabbix_mcp_public_url"], "https://{{ zabbix_mcp_hostname }}"
        )

    def test_report_download_links_stay_off(self):
        config = tomllib.loads(render("config.toml.j2"))
        self.assertIs(config["reporting"]["download_urls"], False)

    def test_empty_auth_token_fails_closed(self):
        with self.assertRaises(tomllib.TOMLDecodeError):
            tomllib.loads(render("config.toml.j2", zabbix_mcp_auth_token=""))
class ZabbixMcpApacheTest(unittest.TestCase):
    def test_apache_component_is_imported(self):
        imports = [
            (task["ansible.builtin.import_tasks"], task["tags"])
            for task in yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
        ]
        self.assertEqual(
            [name for name, _ in imports[:4]],
            ["user.yml", "app.yml", "service.yml", "apache.yml"],
        )
        self.assertEqual(imports[3][1], ["zabbix_mcp_apache"])
        roles = [
            dep["role"]
            for dep in yaml.safe_load((ROLE / "meta" / "main.yml").read_text())[
                "dependencies"
            ]
        ]
        self.assertIn("httpd", roles)

    def test_vhost_proxies_to_the_loopback_listener(self):
        lines = [
            line.strip() for line in render("zabbix-mcp.rewse.jp.conf.j2").splitlines()
        ]
        for expected in (
            "ServerName zabbix-mcp.rewse.jp",
            "ProxyPreserveHost on",
            "ProxyPass / http://127.0.0.1:8081/ flushpackets=on",
            "ProxyPassReverse / http://127.0.0.1:8081/",
            "SSLCertificateFile /etc/letsencrypt/live/rewse.jp/fullchain.pem",
        ):
            with self.subTest(line=expected):
                self.assertIn(expected, lines)

    def test_vhost_allows_only_listed_networks(self):
        text = render("zabbix-mcp.rewse.jp.conf.j2")
        allowed = {
            value
            for line in text.splitlines()
            if line.strip().startswith("Require ip ")
            for value in line.split()[2:]
        }
        expected = {"127.0.0.1", "::1"}
        for value in NETWORKS.values():
            expected.update([value] if isinstance(value, str) else value)
        self.assertEqual(allowed, expected)
        self.assertNotIn("Require all granted", text)


if __name__ == "__main__":
    unittest.main()
