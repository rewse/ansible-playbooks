#!/usr/bin/env python3
"""Regression tests for the CloudFront origin configuration."""

import configparser
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

import jinja2
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROLES = REPO_ROOT / "roles"
HTTPD = ROLES / "httpd"
INVENTORY = REPO_ROOT / "inventory"
SITE = INVENTORY / "group_vars" / "all" / "site.yml"

OFFICE_EXPRESSION = re.compile(
    r"""^\{\{ lookup\('pipe', 'op read "op://ansible/[0-9a-z]{26}/ipv4"'\) """
    r"""\| split\(','\) \}\}$"""
)


class SiteTest(unittest.TestCase):
    # The only IPv4 literals site.yml may hold; the office egress ranges live
    # in 1Password.
    IPV4_ALLOWLIST = ("10.0.0.0/16", "106.163.184.9/32", "192.168.0.0/24")

    def test_site_holds_no_office_cidr_literals(self):
        text = SITE.read_text()
        literals = re.findall(r"(?<![\d.])\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?", text)
        self.assertEqual(sorted(set(literals)), sorted(self.IPV4_ALLOWLIST))
        self.assertNotIn("w.amazon.com", text)
        value = yaml.safe_load(text)["networks"]["office_public_ipv4"]
        self.assertIsInstance(value, str)
        self.assertRegex(value, OFFICE_EXPRESSION)


def render(name: str, **variables) -> str:
    environment = jinja2.Environment(
        loader=jinja2.FileSystemLoader(HTTPD / "templates"),
        undefined=jinja2.StrictUndefined,
    )
    environment.filters["comment"] = lambda text: f"#\n# {text}\n#"
    environment.filters["regex_escape"] = re.escape
    template = environment.get_template(name)
    return template.render(ansible_managed="Ansible managed", **variables)


class RemoteIpTest(unittest.TestCase):
    def render(self, prefixes: list[str]) -> str:
        return render("remoteip.conf.j2", __httpd_remoteip_cloudfront_prefixes=prefixes)

    def test_remoteip_trusts_only_cloudfront_origin_facing(self):
        text = self.render(["130.176.0.0/18"])
        self.assertRegex(text, r"(?m)^RemoteIPHeader X-Forwarded-For$")
        self.assertEqual(
            re.findall(r"(?m)^RemoteIPTrustedProxy (.+)$", text), ["130.176.0.0/18"]
        )
        self.assertNotIn("RemoteIPInternalProxy", text)

    def test_template_starts_with_ansible_managed(self):
        for name in ("remoteip.conf.j2", "fail2ban-cloudfront.conf.j2"):
            text = (HTTPD / "templates" / name).read_text()
            self.assertTrue(text.startswith("{{ ansible_managed | comment }}"), name)

    def test_fail2ban_never_bans_cloudfront(self):
        # If an edge address ever shows up as the client, banning it would
        # deny every visitor that CloudFront routes through it.
        prefixes = ["130.176.0.0/18", "64.252.64.0/18"]
        text = render(
            "fail2ban-cloudfront.conf.j2",
            __httpd_remoteip_cloudfront_prefixes=prefixes,
            networks={"home_public_ipv4": "106.163.184.9/32"},
        )
        parser = configparser.ConfigParser(interpolation=None)
        parser.read_string(
            "\n".join(line for line in text.splitlines() if not line.startswith("#"))
        )
        self.assertEqual(parser.sections(), [])
        self.assertEqual(
            parser.defaults()["ignoreip"].split(),
            ["127.0.0.1/8", "::1", "106.163.184.9/32", *prefixes],
        )

    def test_fail2ban_exemption_uses_the_same_ranges(self):
        tasks = yaml.safe_load((HTTPD / "tasks" / "remoteip.yml").read_text())
        names = [task["name"] for task in tasks]
        template = next(
            task
            for task in tasks
            if task.get("ansible.builtin.template", {}).get("src")
            == "fail2ban-cloudfront.conf.j2"
        )
        self.assertEqual(
            template["ansible.builtin.template"]["dest"],
            "/etc/fail2ban/jail.d/00-cloudfront.conf",
        )
        self.assertEqual(template["notify"], "Restart fail2ban")
        self.assertGreater(
            names.index(template["name"]),
            names.index("remoteip | Check CloudFront origin-facing prefixes"),
        )

    def test_no_jail_replaces_the_exemption(self):
        # A jail's own ignoreip would replace the [DEFAULT] one, CloudFront
        # included.
        found = [
            str(path.relative_to(REPO_ROOT))
            for path in sorted(ROLES.rglob("*"))
            if path.is_file()
            and path.name != "fail2ban-cloudfront.conf.j2"
            and re.search(r"(?m)^\s*ignoreip\s*=", path.read_text(errors="ignore"))
        ]
        self.assertEqual(found, [])

    def test_log_formats_use_the_client_address(self):
        text = (HTTPD / "files" / "log-format.conf").read_text()
        formats = {
            name: spec
            for spec, name in re.findall(r'(?m)^LogFormat "(.*)" (\S+)$', text)
        }
        self.assertEqual(sorted(formats), ["combined", "vhost_combined"])
        for spec in formats.values():
            self.assertIn("%a", spec)
            self.assertNotIn("%h", spec)

    def test_no_role_logs_the_connection_address(self):
        # Behind CloudFront %h is the edge server, so a log fail2ban reads must
        # use %a, the client address mod_remoteip restores.
        directive = re.compile(r"(?m)^\s*(?:CustomLog|LogFormat)\b.*$")
        lines = [
            f"{path.relative_to(REPO_ROOT)}: {line.strip()}"
            for path in sorted((REPO_ROOT / "roles").rglob("*"))
            if path.is_file() and path.suffix in (".conf", ".j2")
            for line in directive.findall(path.read_text())
        ]
        self.assertIn(
            "roles/teslamate/templates/grafana.rewse.jp.conf.j2: "
            'CustomLog ${APACHE_LOG_DIR}/grafana_basic_auth.log "%v:%p %a basic '
            '%{end:[%d/%b/%Y:%H:%M:%S %z]}t \\"%r\\" %>s %O" env=grafana_basic_auth',
            lines,
        )
        self.assertEqual([line for line in lines if "%h" in line], [])


class RemoteIpDriftTest(unittest.TestCase):
    SCRIPT = HTTPD / "files" / "remoteip-drift"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = pathlib.Path(tmp.name)
        self.ranges = self.root / "ip-ranges.json"
        self.conf = self.root / "remoteip.conf"

    def write_ranges(self, prefixes: dict[str, str]) -> None:
        self.ranges.write_text(
            json.dumps(
                {
                    "prefixes": [
                        {"ip_prefix": prefix, "service": service}
                        for prefix, service in prefixes.items()
                    ]
                }
            )
        )

    def write_conf(self, prefixes: list[str]) -> None:
        self.conf.write_text(
            render("remoteip.conf.j2", __httpd_remoteip_cloudfront_prefixes=prefixes)
        )

    def run_script(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-I",
                str(self.SCRIPT),
                self.ranges.as_uri(),
                str(self.conf),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_reports_zero_when_the_trust_list_is_current(self):
        self.write_ranges(
            {"130.176.0.0/18": "CLOUDFRONT_ORIGIN_FACING", "3.5.140.0/22": "AMAZON"}
        )
        self.write_conf(["130.176.0.0/18"])

        result = self.run_script()

        self.assertEqual(
            (result.returncode, result.stdout, result.stderr), (0, "0\n", "")
        )

    def test_counts_published_prefixes_the_trust_list_lacks(self):
        self.write_ranges(
            {
                "130.176.0.0/18": "CLOUDFRONT_ORIGIN_FACING",
                "64.252.64.0/18": "CLOUDFRONT_ORIGIN_FACING",
                "15.158.0.0/16": "CLOUDFRONT_ORIGIN_FACING",
            }
        )
        self.write_conf(["130.176.0.0/18"])

        self.assertEqual(self.run_script().stdout, "2\n")

    def test_prints_nothing_when_a_source_cannot_be_read(self):
        self.write_conf(["130.176.0.0/18"])
        self.assertEqual(self.run_script().stdout, "")
        self.ranges.write_text("not json")
        self.assertEqual(self.run_script().stdout, "")
        self.write_ranges({"3.5.140.0/22": "AMAZON"})
        self.assertEqual(self.run_script().stdout, "")
        self.write_ranges({"130.176.0.0/18": "CLOUDFRONT_ORIGIN_FACING"})
        self.conf.unlink()
        result = self.run_script()
        self.assertEqual((result.stdout, result.stderr), ("", ""))

    def test_agent_runs_the_script_against_the_same_sources(self):
        text = render(
            "remoteip-drift.conf.j2",
            httpd_remoteip_ip_ranges_url="https://ip-ranges.amazonaws.com/ip-ranges.json",
        )
        self.assertIn(
            "UserParameter=apache.remoteip.missing_prefixes,"
            "/usr/lib/zabbix/agentscripts/remoteip-drift "
            "https://ip-ranges.amazonaws.com/ip-ranges.json "
            "/etc/apache2/conf-available/remoteip.conf",
            text.splitlines(),
        )
        imports = yaml.safe_load((HTTPD / "tasks" / "main.yml").read_text())
        names = [task["ansible.builtin.import_tasks"] for task in imports]
        self.assertEqual(
            names.index("remoteip_drift.yml"), names.index("remoteip.yml") + 1
        )
        self.assertIn(
            {
                "name": "Import remoteip_drift tasks",
                "ansible.builtin.import_tasks": "remoteip_drift.yml",
                "tags": ["httpd_remoteip_drift"],
            },
            imports,
        )


class OriginGateTest(unittest.TestCase):
    # Regex metacharacters check that the value is matched literally.
    TOKEN = "fake.origin+token"
    OFFICE = ("198.51.100.0/24", "203.0.113.0/24")
    EXEMPT_NETWORKS = (
        "aws_private_ipv4",
        "aws_public_ipv6",
        "home_private_ipv4",
        "home_private_ipv6",
        "home_public_ipv6",
    )

    def setUp(self):
        self.networks = yaml.safe_load(SITE.read_text())["networks"]
        self.networks["office_public_ipv4"] = list(self.OFFICE)

    def render(self, enforce: bool) -> str:
        return render(
            "cloudfront-origin.conf.j2",
            httpd_cloudfront_origin_enforce=enforce,
            httpd_cloudfront_origin_verify_token=self.TOKEN,
            networks=self.networks,
        )

    @staticmethod
    def directives(text: str) -> list[str]:
        return [
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]

    def test_header_is_matched_exactly_and_removed(self):
        for enforce in (False, True):
            lines = self.directives(self.render(enforce))
            self.assertIn(
                f'SetEnvIf X-Origin-Verify "^{re.escape(self.TOKEN)}$" cloudfront_origin',
                lines,
            )
            self.assertIn("RequestHeader unset X-Origin-Verify", lines)

    def test_not_enforced_renders_no_require(self):
        text = self.render(False)
        self.assertNotIn("Require", text)
        self.assertNotIn("<If", text)

    def test_enforced_denies_only_outside_the_gate(self):
        text = self.render(True)
        sections = re.findall(r'(?ms)^<If "(.*?)">\n(.*?)^</If>$', text)
        self.assertEqual(len(sections), 1)
        self.assertEqual(text.count("<If"), 1)
        condition, body = sections[0]
        self.assertEqual(self.directives(body), ["Require all denied"])
        self.assertIn("reqenv('cloudfront_origin') != '1'", condition)
        # An internal redirect renames the variable with a REDIRECT_ prefix.
        self.assertIn("reqenv('REDIRECT_cloudfront_origin') != '1'", condition)
        exempt = ["127.0.0.1", "::1"] + [
            self.networks[name] for name in self.EXEMPT_NETWORKS
        ]
        terms = re.findall(r"! -R '([^']+)'", condition)
        self.assertEqual(sorted(terms), sorted(exempt))
        self.assertNotIn(self.networks["home_public_ipv4"], condition)
        for cidr in self.OFFICE:
            self.assertNotIn(cidr, text)
        self.assertEqual(
            re.findall(r"(?m)^\s*(Require\b.*?)\s*$", text), ["Require all denied"]
        )
        self.assertNotIn("<Location", text)
        self.assertNotIn("RequireAny", text)

    def test_exempt_networks_may_be_lists(self):
        # site.yml allows each network to be a CIDR or a list of CIDRs.
        self.networks["aws_public_ipv6"] = ["2001:db8:1::/56", "2001:db8:2::/56"]
        self.networks["home_private_ipv4"] = ["192.0.2.0/24"]
        ((condition, _),) = re.findall(
            r'(?ms)^<If "(.*?)">\n(.*?)^</If>$', self.render(True)
        )
        terms = re.findall(r"! -R '([^']+)'", condition)
        for cidr in ("2001:db8:1::/56", "2001:db8:2::/56", "192.0.2.0/24"):
            self.assertIn(cidr, terms)
        self.assertNotIn("[", condition)
        self.assertEqual(len(terms), 8)

    def test_no_other_if_sections(self):
        # Apache merges If sections last, so another one could override the deny.
        # The fail2ban ban script writes deny-only sections, which
        # tests/test_fail2ban_apache.py checks; nothing else may write one.
        allowed = {
            HTTPD / "templates" / "cloudfront-origin.conf.j2",
            HTTPD / "files" / "fail2ban-apache-deny",
        }
        found = [
            str(path.relative_to(REPO_ROOT))
            for path in sorted(ROLES.rglob("*"))
            if path.is_file()
            and path not in allowed
            and re.search(r"<(?:If|ElseIf|Else)\b", path.read_text(errors="ignore"))
        ]
        self.assertEqual(found, [])
        for path in allowed:
            self.assertRegex(path.read_text(), r"<If\b", path)

    def test_hotel_gets_the_same_gate(self):
        dependencies = yaml.safe_load(
            (ROLES / "homeassistant_ha_secondary" / "meta" / "main.yml").read_text()
        )["dependencies"]
        self.assertIn("httpd", [dependency["role"] for dependency in dependencies])
        values = [
            yaml.safe_load(
                (INVENTORY / "group_vars" / group / "httpd.yml").read_text()
            )["httpd_cloudfront_origin_enforce"]
            for group in ("home_primary", "home_secondary")
        ]
        self.assertEqual(values[0], values[1])
        self.assertIsInstance(values[0], bool)
        default = yaml.safe_load((HTTPD / "defaults" / "main.yml").read_text())
        self.assertIs(default["httpd_cloudfront_origin_enforce"], False)

    def test_gate_is_deployed_like_the_pentest_header(self):
        tasks = yaml.safe_load((HTTPD / "tasks" / "cloudfront_origin.yml").read_text())
        template = next(task for task in tasks if "ansible.builtin.template" in task)
        self.assertEqual(
            template["ansible.builtin.template"]["dest"],
            "/etc/apache2/conf-available/cloudfront-origin.conf",
        )
        self.assertEqual(template["ansible.builtin.template"]["mode"], "0640")
        self.assertIs(template["diff"], False)
        imports = yaml.safe_load((HTTPD / "tasks" / "main.yml").read_text())
        self.assertIn(
            {
                "name": "Import cloudfront_origin tasks",
                "ansible.builtin.import_tasks": "cloudfront_origin.yml",
                "tags": ["httpd_cloudfront_origin"],
            },
            imports,
        )


if __name__ == "__main__":
    unittest.main()
