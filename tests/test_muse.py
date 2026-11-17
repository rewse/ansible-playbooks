"""Regression tests for the muse role."""

import configparser
import pathlib
import re
import unittest

import jinja2
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROLE = REPO_ROOT / "roles" / "muse"
RULES = "/etc/nftables.d/muse.nft"


def role_vars() -> dict:
    return yaml.safe_load((ROLE / "vars" / "main.yml").read_text())


def render_rules() -> str:
    environment = jinja2.Environment(
        loader=jinja2.FileSystemLoader(ROLE / "templates"),
        undefined=jinja2.StrictUndefined,
        keep_trailing_newline=True,
    )
    environment.filters["comment"] = lambda text: f"#\n# {text}\n#"
    variables = role_vars()
    return environment.get_template("muse.nft.j2").render(
        ansible_managed="Ansible managed",
        muse_firewall_local_tcp_ports=variables["muse_firewall_local_tcp_ports"],
        muse_firewall_zabbix_ports=variables["muse_firewall_zabbix_ports"],
        muse_uid=variables["muse_uid"],
    )


def rule_lines(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def chain(text: str, name: str) -> list[str]:
    lines = rule_lines(text)
    start = lines.index(f"chain {name} {{") + 1
    return lines[start : lines.index("}", start)]


class PgpassTest(unittest.TestCase):
    def test_pgpass_targets_only_rewse_pg(self):
        hosts = [entry["host"] for entry in role_vars()["muse_pgpass_entries"]]
        self.assertEqual(hosts, ["rewse-pg.rewse.jp"])


class FirewallRulesTest(unittest.TestCase):
    # Docker and fail2ban keep their own tables in the same ruleset, so the
    # file must replace only its own table.
    def test_rules_replace_only_their_own_table(self):
        text = render_rules()
        self.assertNotIn("flush", text)
        self.assertEqual(
            set(
                re.findall(r"^\s*(?:table|delete table) (\S+ \S+)", text, re.MULTILINE)
            ),
            {"inet muse"},
        )
        lines = rule_lines(text)
        self.assertLess(
            lines.index("delete table inet muse"), lines.index("table inet muse {")
        )

    def test_only_new_tcp_connections_of_muse_are_filtered(self):
        output = chain(render_rules(), "output")
        self.assertEqual(
            output,
            [
                "type filter hook output priority filter; policy accept;",
                f"meta skuid {role_vars()['muse_uid']}"
                + " meta l4proto tcp ct state new jump muse",
            ],
        )

    def test_muse_cannot_reach_this_host_or_its_containers(self):
        rules = chain(render_rules(), "muse")
        for rule in (
            "fib daddr type local reject with tcp reset",
            'oifname "br-*" reject with tcp reset',
            'oifname "docker0" reject with tcp reset',
        ):
            with self.subTest(rule=rule):
                self.assertIn(rule, rules)

    def test_muse_cannot_reach_zabbix_anywhere(self):
        rules = chain(render_rules(), "muse")
        self.assertEqual(role_vars()["muse_firewall_zabbix_ports"], [10050, 10051])
        self.assertEqual(rules[0], "tcp dport { 10050, 10051 } reject with tcp reset")

    def test_only_dns_and_https_on_this_host_are_allowed(self):
        rules = chain(render_rules(), "muse")
        self.assertEqual(role_vars()["muse_firewall_local_tcp_ports"], [53, 443])
        allow = "fib daddr type local tcp dport { 53, 443 } return"
        self.assertEqual([r for r in rules if r.endswith("return")], [allow])
        self.assertLess(
            rules.index(allow),
            rules.index("fib daddr type local reject with tcp reset"),
        )


class FirewallServiceTest(unittest.TestCase):
    def unit(self) -> configparser.ConfigParser:
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.optionxform = str  # pyright: ignore[reportAttributeAccessIssue]  # systemd keys are case-sensitive
        parser.read(ROLE / "files" / "muse-firewall.service")
        return parser

    def test_unit_loads_only_the_muse_rules(self):
        service = self.unit()["Service"]
        self.assertEqual(service["ExecStart"], f"/usr/sbin/nft -f {RULES}")
        self.assertEqual(service["ExecReload"], f"/usr/sbin/nft -f {RULES}")
        self.assertEqual(service["ExecStop"], "/usr/sbin/nft delete table inet muse")

    def test_rules_load_before_the_network_comes_up(self):
        unit = self.unit()
        self.assertIn("network-pre.target", unit["Unit"]["Before"].split())
        self.assertEqual(unit["Install"]["WantedBy"], "sysinit.target")

    def test_tasks_validate_and_start_the_rules(self):
        tasks = yaml.safe_load((ROLE / "tasks" / "firewall.yml").read_text())
        template = next(t for t in tasks if "ansible.builtin.template" in t)
        self.assertEqual(template["ansible.builtin.template"]["dest"], RULES)
        self.assertEqual(
            template["ansible.builtin.template"]["validate"], "nft -c -f %s"
        )
        service = next(t for t in tasks if "ansible.builtin.systemd" in t)
        self.assertEqual(
            service["ansible.builtin.systemd"],
            {
                "name": "muse-firewall",
                "enabled": True,
                "state": "started",
                "daemon_reload": True,
            },
        )
        # The stock nftables.service loads /etc/nftables.conf, which flushes
        # the whole ruleset, Docker's tables included.
        for path in sorted(ROLE.rglob("*")):
            if path.is_file():
                with self.subTest(path=str(path)):
                    self.assertNotIn("nftables.conf", path.read_text())
                    self.assertNotIn("nftables.service", path.read_text())

    def test_component_is_imported(self):
        main = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
        firewall = next(
            t for t in main if t["ansible.builtin.import_tasks"] == "firewall.yml"
        )
        self.assertEqual(firewall["tags"], ["muse_firewall"])


if __name__ == "__main__":
    unittest.main()
