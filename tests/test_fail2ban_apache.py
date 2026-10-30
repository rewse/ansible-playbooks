#!/usr/bin/env python3
"""Regression tests for the fail2ban bans that Apache enforces."""

import configparser
import ipaddress
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

import jinja2
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROLES = REPO_ROOT / "roles"
HTTPD = ROLES / "httpd"
SCRIPT = HTTPD / "files" / "fail2ban-apache-deny"
STATE_DIR = "/var/lib/fail2ban-apache-deny"
# Module directories of the Apache builds a developer may have locally.
APACHE_MODULE_DIRS = (
    pathlib.Path("/usr/lib/apache2/modules"),
    pathlib.Path("/usr/libexec/apache2"),
)


def load_yaml(path: pathlib.Path):
    return yaml.safe_load(path.read_text())


def jail_files() -> list[pathlib.Path]:
    return sorted(ROLES.glob("*/templates/fail2ban-jail.conf.j2"))


def jail_sections(path: pathlib.Path) -> configparser.SectionProxy:
    parser = configparser.ConfigParser(interpolation=None)
    lines = [
        line
        for line in path.read_text().splitlines()
        if not line.lstrip().startswith(("#", "{{"))
    ]
    parser.read_string("\n".join(lines))
    (section,) = parser.sections()
    return parser[section]


def render(name: str, **variables) -> str:
    environment = jinja2.Environment(
        loader=jinja2.FileSystemLoader(HTTPD / "templates"),
        undefined=jinja2.StrictUndefined,
    )
    environment.filters["comment"] = lambda text: f"#\n# {text}\n#"
    return environment.get_template(name).render(
        ansible_managed="Ansible managed", **variables
    )


def if_sections(text: str) -> list[tuple[str, str]]:
    return re.findall(r'(?ms)^<If "(.*?)">\n(.*?)^</If>$', text)


class ApacheDenyScriptTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = pathlib.Path(tmp.name)
        self.state = self.root / "state"
        self.state.mkdir()
        self.calls = self.root / "systemctl.calls"
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        stub = bin_dir / "systemctl"
        stub.write_text(f'#!/bin/sh\necho "$*" >> "{self.calls}"\n')
        stub.chmod(0o755)
        self.env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}

    def run_script(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-I", str(SCRIPT), str(self.state), *args],
            capture_output=True,
            text=True,
            env=self.env,
            check=False,
        )

    def seed(self, jail: str, addresses: list[str]) -> None:
        # Many bans at once, without starting the script for each.
        (self.state / f"{jail}.bans").write_text("".join(f"{a}\n" for a in addresses))

    def conf(self, jail: str) -> str:
        return (self.state / f"{jail}.conf").read_text()

    def reloads(self) -> list[str]:
        if not self.calls.exists():
            return []
        return self.calls.read_text().splitlines()

    def test_ban_denies_the_address_server_wide(self):
        result = self.run_script("ban", "nvr", "203.0.113.7")

        self.assertEqual(result.returncode, 0, result.stderr)
        sections = if_sections(self.conf("nvr"))
        self.assertEqual(sections, [("-R '203.0.113.7'", "    Require all denied\n")])
        self.assertEqual(self.reloads(), ["try-reload-or-restart apache2"])

    def test_unbanning_the_last_address_leaves_no_section(self):
        self.run_script("ban", "nvr", "203.0.113.7")
        result = self.run_script("unban", "nvr", "203.0.113.7")

        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.conf("nvr")
        self.assertNotIn("<If", text)
        self.assertNotIn("Require", text)
        self.assertEqual(len(self.reloads()), 2)

    def test_jails_keep_separate_files(self):
        self.run_script("ban", "nvr", "203.0.113.7")
        self.run_script("ban", "couchdb", "198.51.100.9")
        self.run_script("unban", "nvr", "203.0.113.7")

        self.assertNotIn("<If", self.conf("nvr"))
        self.assertEqual(if_sections(self.conf("couchdb"))[0][0], "-R '198.51.100.9'")

    def test_flush_clears_the_jail(self):
        self.run_script("ban", "nvr", "203.0.113.7")
        self.run_script("ban", "nvr", "2001:db8::1")
        result = self.run_script("flush", "nvr")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("<If", self.conf("nvr"))
        self.assertEqual(len(self.reloads()), 3)

    def test_flush_without_bans_writes_an_empty_file_and_skips_the_reload(self):
        result = self.run_script("flush", "nvr")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("<If", self.conf("nvr"))
        self.assertEqual(self.reloads(), [])

    def test_repeated_ban_and_unknown_unban_change_nothing(self):
        self.run_script("ban", "nvr", "203.0.113.7")
        self.run_script("ban", "nvr", "203.0.113.7")
        self.run_script("unban", "nvr", "198.51.100.9")

        self.assertEqual(len(if_sections(self.conf("nvr"))), 1)
        self.assertEqual(len(self.reloads()), 1)

    def test_ipv6_addresses_are_written_in_canonical_form(self):
        self.run_script("ban", "nvr", "2001:DB8:0:0::1")

        self.assertEqual(if_sections(self.conf("nvr"))[0][0], "-R '2001:db8::1'")

    def test_many_addresses_are_split_into_short_sections(self):
        addresses = [str(ipaddress.ip_address("198.18.0.0") + i) for i in range(250)]
        self.seed("nvr", addresses[:-1])
        self.assertEqual(self.run_script("ban", "nvr", addresses[-1]).returncode, 0)

        sections = if_sections(self.conf("nvr"))
        self.assertEqual(len(sections), 3)
        terms = []
        for condition, body in sections:
            self.assertEqual(body, "    Require all denied\n")
            found = re.findall(r"-R '([^']+)'", condition)
            self.assertEqual(condition, " || ".join(f"-R '{a}'" for a in found))
            self.assertLessEqual(len(found), 100)
            terms += found
        self.assertEqual(sorted(terms), sorted(addresses))

    def test_rejects_anything_but_an_address(self):
        for address in (
            "203.0.113.7' || true || '",
            "203.0.113.0/24",
            "example.com",
            "fe80::1%eth0",
            'fe80::1%x"y',
        ):
            with self.subTest(address=address):
                result = self.run_script("ban", "nvr", address)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.state / "nvr.conf").exists())
        self.assertEqual(self.reloads(), [])

    def test_flush_clears_a_ban_list_with_unreadable_lines(self):
        (self.state / "nvr.bans").write_text("203.0.113.7\nnot-an-address\n")

        self.assertEqual(self.run_script("flush", "nvr").returncode, 0)
        self.assertNotIn("<If", self.conf("nvr"))

    def test_ban_skips_unreadable_lines_in_the_ban_list(self):
        (self.state / "nvr.bans").write_text("not-an-address\nfe80::1%x\n")

        self.assertEqual(self.run_script("ban", "nvr", "203.0.113.7").returncode, 0)
        self.assertEqual(if_sections(self.conf("nvr"))[0][0], "-R '203.0.113.7'")

    def test_rejects_a_jail_name_that_leaves_the_directory(self):
        result = self.run_script("ban", "../nvr", "203.0.113.7")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(self.root.glob("*.conf")), [])

    @unittest.skipUnless(
        shutil.which("httpd") or shutil.which("apache2"), "no Apache to test with"
    )
    def test_apache_accepts_the_generated_file(self):
        module_dir = next(
            (d for d in APACHE_MODULE_DIRS if (d / "mod_authz_core.so").exists()),
            None,
        )
        if module_dir is None:
            self.skipTest("no Apache modules found")
        self.seed(
            "nvr", [str(ipaddress.ip_address("198.18.0.0") + i) for i in range(5000)]
        )
        self.assertEqual(self.run_script("ban", "nvr", "2001:db8::1").returncode, 0)
        modules = [
            f"LoadModule {name}_module {module_dir}/mod_{name}.so"
            for name in ("mpm_prefork", "authz_core", "unixd")
            if (module_dir / f"mod_{name}.so").exists()
        ]
        config = self.root / "httpd.conf"
        config.write_text(
            "\n".join(
                [
                    *modules,
                    "Listen 127.0.0.1:58080",
                    f"PidFile {self.root}/httpd.pid",
                    f"ErrorLog {self.root}/error.log",
                    "ServerName localhost",
                    f"IncludeOptional {self.state}/*.conf",
                    f"IncludeOptional {self.root}/missing/*.conf",
                ]
            )
            + "\n"
        )
        binary = shutil.which("httpd") or shutil.which("apache2")
        assert binary is not None
        result = subprocess.run(
            [binary, "-t", "-f", str(config)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


class ApacheDenyActionTest(unittest.TestCase):
    def test_action_mirrors_every_ban_event(self):
        text = render(
            "fail2ban-action-apache-deny.conf.j2", httpd_fail2ban_state_dir=STATE_DIR
        )
        parser = configparser.ConfigParser(interpolation=None)
        parser.read_string(
            "\n".join(line for line in text.splitlines() if not line.startswith("#"))
        )
        definition = parser["Definition"]
        command = f"/usr/local/sbin/fail2ban-apache-deny {STATE_DIR}"
        self.assertEqual(definition["actionstart"], f"{command} flush <name>")
        self.assertEqual(definition["actionstop"], f"{command} flush <name>")
        self.assertEqual(definition["actionflush"], f"{command} flush <name>")
        self.assertEqual(definition["actionban"], f"{command} ban <name> <ip>")
        self.assertEqual(definition["actionunban"], f"{command} unban <name> <ip>")

    def test_apache_includes_the_generated_files_optionally(self):
        text = render(
            "fail2ban-apache-deny.conf.j2", httpd_fail2ban_state_dir=STATE_DIR
        )
        directives = [
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertEqual(directives, [f"IncludeOptional {STATE_DIR}/*.conf"])

    def test_state_dir_is_one_value(self):
        variables = load_yaml(HTTPD / "vars" / "main.yml")
        self.assertEqual(variables["httpd_fail2ban_state_dir"], STATE_DIR)

    def test_component_is_imported_and_self_contained(self):
        imports = {
            task["ansible.builtin.import_tasks"]: task["tags"]
            for task in load_yaml(HTTPD / "tasks" / "main.yml")
        }
        self.assertEqual(imports.get("fail2ban.yml"), ["httpd_fail2ban"])
        tasks = load_yaml(HTTPD / "tasks" / "fail2ban.yml")
        modules = {
            (module, task[module].get("dest") or task[module].get("path"))
            for task in tasks
            for module in task
            if module.startswith("ansible.builtin.")
            and module != "ansible.builtin.command"
        }
        self.assertIn(
            ("ansible.builtin.file", "{{ httpd_fail2ban_state_dir }}"), modules
        )
        self.assertIn(
            ("ansible.builtin.copy", "/usr/local/sbin/fail2ban-apache-deny"), modules
        )
        self.assertIn(
            ("ansible.builtin.template", "/etc/fail2ban/action.d/apache-deny.conf"),
            modules,
        )
        self.assertIn(
            (
                "ansible.builtin.template",
                "/etc/apache2/conf-available/fail2ban-apache-deny.conf",
            ),
            modules,
        )
        enables = [
            task["ansible.builtin.command"]
            for task in tasks
            if "ansible.builtin.command" in task
        ]
        self.assertEqual(enables, ["a2enconf fail2ban-apache-deny"])


class JailActionTest(unittest.TestCase):
    def test_every_http_jail_bans_in_apache_and_at_the_firewall(self):
        files = jail_files()
        self.assertEqual(
            [path.parent.parent.name for path in files],
            [
                "couchdb",
                "filebrowser",
                "gnucash_quick_expense",
                "homeassistant",
                "litellm",
                "nvr",
                "teslamate",
                "zabbix_mcp",
                "zabbix_server",
            ],
        )
        for path in files:
            with self.subTest(path=str(path.relative_to(REPO_ROOT))):
                section = jail_sections(path)
                self.assertEqual(section["port"], "http,https")
                self.assertEqual(
                    section["action"].split(), ["%(action_)s", "apache-deny"]
                )

    def test_sshd_jail_keeps_only_the_firewall(self):
        text = (ROLES / "fail2ban" / "templates" / "sshd.conf.j2").read_text()
        self.assertNotIn("apache-deny", text)
        self.assertNotRegex(text, r"(?m)^action\s*=")

    def test_http_jail_roles_depend_on_httpd(self):
        # The action file comes from the httpd role, so it has to be in place
        # before a jail that names it starts.
        for path in jail_files():
            role = path.parent.parent
            with self.subTest(role=role.name):
                dependencies = load_yaml(role / "meta" / "main.yml")["dependencies"]
                self.assertIn("httpd", [d["role"] for d in dependencies])


if __name__ == "__main__":
    unittest.main()
