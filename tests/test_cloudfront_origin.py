#!/usr/bin/env python3
"""Regression tests for the CloudFront origin configuration."""

import pathlib
import re
import unittest

import jinja2
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
HTTPD = REPO_ROOT / "roles" / "httpd"
SITE = REPO_ROOT / "inventory" / "group_vars" / "all" / "site.yml"

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


class RemoteIpTest(unittest.TestCase):
    def render(self, prefixes: list[str]) -> str:
        environment = jinja2.Environment(
            loader=jinja2.FileSystemLoader(HTTPD / "templates"),
            undefined=jinja2.StrictUndefined,
        )
        environment.filters["comment"] = lambda text: f"#\n# {text}\n#"
        template = environment.get_template("remoteip.conf.j2")
        return template.render(
            __httpd_remoteip_cloudfront_prefixes=prefixes,
            ansible_managed="Ansible managed",
        )

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


if __name__ == "__main__":
    unittest.main()
