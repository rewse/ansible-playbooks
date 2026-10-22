#!/usr/bin/env python3
"""Regression tests for the CloudFront origin configuration."""

import pathlib
import re
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
    def test_site_holds_no_office_cidr_literals(self):
        text = SITE.read_text()
        for literal in ("13.113.", "15.248.", "w.amazon.com"):
            self.assertNotIn(literal, text)
        value = yaml.safe_load(text)["networks"]["office_public_ipv4"]
        self.assertIsInstance(value, str)
        self.assertRegex(value, OFFICE_EXPRESSION)


def render(name: str, **variables) -> str:
    environment = jinja2.Environment(
        loader=jinja2.FileSystemLoader(HTTPD / "templates"),
        undefined=jinja2.StrictUndefined,
    )
    environment.filters["comment"] = lambda text: f"#\n# {text}\n#"
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
        text = (HTTPD / "templates" / "remoteip.conf.j2").read_text()
        self.assertTrue(text.startswith("{{ ansible_managed | comment }}"))

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


class OriginGateTest(unittest.TestCase):
    TOKEN = "fake-origin-token"
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
                f'SetEnvIf X-Origin-Verify "^{self.TOKEN}$" cloudfront_origin', lines
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
        exempt = ["127.0.0.1", "::1"] + [
            self.networks[name] for name in self.EXEMPT_NETWORKS
        ]
        terms = re.findall(r"! -R '([^']+)'", condition)
        self.assertEqual(sorted(terms), sorted(exempt))
        self.assertNotIn(self.networks["home_public_ipv4"], condition)
        for cidr in self.OFFICE:
            self.assertNotIn(cidr, text)
        self.assertNotIn("<Location", text)
        self.assertNotIn("RequireAny", text)

    def test_gate_cannot_grant_access(self):
        for enforce in (False, True):
            requires = re.findall(r"(?m)^\s*(Require\b.*)$", self.render(enforce))
            self.assertEqual(
                [line for line in requires if line.strip() != "Require all denied"],
                [],
            )

    def test_no_other_if_sections(self):
        # Apache merges If sections last, so another one could override the deny.
        gate = HTTPD / "templates" / "cloudfront-origin.conf.j2"
        found = [
            str(path.relative_to(REPO_ROOT))
            for path in sorted(ROLES.rglob("*"))
            if path.is_file()
            and path.suffix in (".conf", ".j2")
            and path != gate
            and re.search(r"<(?:If|ElseIf|Else)\b", path.read_text())
        ]
        self.assertEqual(found, [])

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
