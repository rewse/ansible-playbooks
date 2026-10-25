#!/usr/bin/env python3
"""Contract tests for the zabbix_mcp role."""

import configparser
import pathlib
import re
import tomllib
import unittest

import jinja2
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROLE = REPO_ROOT / "roles" / "zabbix_mcp"
HOSTNAME = "zabbix-mcp.rewse.jp"

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


def access_line(vhost: str, request: str, status: int) -> str:
    # A vhost_combined line as fail2ban sees it, with the timestamp removed.
    return f'{vhost}:443 203.0.113.7 - - [] "{request} HTTP/1.1" {status} 28 "-" "curl" 512'


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
class ZabbixMcpFail2banTest(unittest.TestCase):
    def test_fail2ban_component_is_imported(self):
        imports = {
            task["ansible.builtin.import_tasks"]: task["tags"]
            for task in yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
        }
        self.assertEqual(imports.get("fail2ban.yml"), ["zabbix_mcp_fail2ban"])
        self.assertEqual(list(imports)[-2:], ["apache.yml", "fail2ban.yml"])
        roles = [
            dep["role"]
            for dep in yaml.safe_load((ROLE / "meta" / "main.yml").read_text())[
                "dependencies"
            ]
        ]
        self.assertEqual(roles, ["fail2ban", "httpd"])

    def test_jail_reads_the_apache_log(self):
        parser = configparser.ConfigParser(interpolation=None)
        lines = [
            line
            for line in render("fail2ban-jail.conf.j2").splitlines()
            if not line.lstrip().startswith("#")
        ]
        parser.read_string("\n".join(lines))
        section = parser["zabbix-mcp"]
        self.assertEqual(section["enabled"], "true")
        self.assertEqual(section["backend"], "auto")
        self.assertEqual(section["filter"], "zabbix-mcp")
        self.assertEqual(section["logpath"], "/var/log/apache2/other_vhosts_access.log")

    def test_filter_matches_rejected_tokens_only(self):
        line = next(
            line
            for line in render("fail2ban-filter.conf.j2").splitlines()
            if line.startswith("failregex = ")
        )
        regex = re.compile(
            line.removeprefix("failregex = ").replace("<HOST>", r"(?P<host>\S+)")
        )
        for request in ("POST /mcp", "GET /mcp", "DELETE /mcp"):
            with self.subTest(request=request):
                match = regex.search(access_line(HOSTNAME, request, 401))
                self.assertIsNotNone(match)
                assert match is not None
                self.assertEqual(match["host"], "203.0.113.7")
        for unmatched in (
            # A call with a valid token.
            access_line(HOSTNAME, "POST /mcp", 200),
            # A rejected call on another virtual host.
            access_line("litellm.rewse.jp", "POST /mcp", 401),
            # OAuth discovery, which a client reads before it sends a token.
            access_line(HOSTNAME, "GET /.well-known/oauth-protected-resource", 401),
            # A path that only starts like the endpoint.
            access_line(HOSTNAME, "GET /mcpx", 401),
        ):
            with self.subTest(line=unmatched):
                self.assertIsNone(regex.search(unmatched))


if __name__ == "__main__":
    unittest.main()
