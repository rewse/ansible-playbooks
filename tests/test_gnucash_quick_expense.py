#!/usr/bin/env python3
"""Regression tests for the gnucash_quick_expense role."""

import configparser
import json
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

import jinja2
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROLE = REPO_ROOT / "roles" / "gnucash_quick_expense"


def load_yaml(path: pathlib.Path):
    return yaml.safe_load(path.read_text())


def jail(path: pathlib.Path, section: str) -> configparser.SectionProxy:
    parser = configparser.ConfigParser(interpolation=None)
    lines = [
        line
        for line in path.read_text().splitlines()
        if not line.lstrip().startswith(("#", "{{"))
    ]
    parser.read_string("\n".join(lines))
    return parser[section]


def filter_regex(path: pathlib.Path, variable: str, hostname: str) -> re.Pattern:
    line = next(
        line
        for line in path.read_text().splitlines()
        if line.startswith("failregex = ")
    )
    pattern = line.removeprefix("failregex = ")
    pattern = pattern.replace(
        "{{ " + variable + " | regex_escape }}", re.escape(hostname)
    )
    pattern = pattern.replace("<HOST>", r"(?P<host>\S+)")
    return re.compile(pattern)


def access_line(vhost: str, request: str, status: int) -> str:
    # A vhost_combined line as fail2ban sees it, with the timestamp removed.
    return f'{vhost}:443 203.0.113.7 - - [] "{request} HTTP/1.1" {status} 28 "-" "curl" 512'


def tasks_of(component: str) -> list[dict]:
    return load_yaml(ROLE / "tasks" / f"{component}.yml")


VARS = load_yaml(ROLE / "vars" / "main.yml")


class ComponentsTest(unittest.TestCase):
    def test_main_imports_every_component_with_its_tag(self):
        imports = {
            task["ansible.builtin.import_tasks"]: task["tags"]
            for task in tasks_of("main")
        }
        self.assertEqual(
            imports,
            {
                "user.yml": ["gnucash_quick_expense_user"],
                "app.yml": ["gnucash_quick_expense_app", "update"],
                "service.yml": ["gnucash_quick_expense_service"],
                "apache.yml": ["gnucash_quick_expense_apache"],
                "fail2ban.yml": ["gnucash_quick_expense_fail2ban"],
            },
        )

    def test_role_depends_on_fail2ban_and_httpd(self):
        roles = [
            d["role"] for d in load_yaml(ROLE / "meta" / "main.yml")["dependencies"]
        ]
        self.assertEqual(sorted(roles), ["fail2ban", "httpd"])

    def test_home_primary_runs_the_role(self):
        play = load_yaml(REPO_ROOT / "home-primary.yml")[0]
        roles = [r["role"] for r in play["roles"]]
        self.assertIn("gnucash_quick_expense", roles)
        services = roles[roles.index("couchdb") :]
        self.assertEqual(services, sorted(services))


class AppTest(unittest.TestCase):
    def test_checkout_is_root_owned_and_follows_main(self):
        git = next(
            t["ansible.builtin.git"]
            for t in tasks_of("app")
            if "ansible.builtin.git" in t
        )
        self.assertEqual(
            git["repo"], "https://github.com/rewse/gnucash-quick-expense.git"
        )
        self.assertEqual(git["dest"], "/opt/gnucash-quick-expense")
        self.assertEqual(git["version"], "main")
        sync = next(
            t
            for t in tasks_of("app")
            if "uv sync" in str(t.get("ansible.builtin.command", ""))
        )
        self.assertEqual(sync["become_user"], "gnucash-quick-expense")
        self.assertIn("--frozen", sync["ansible.builtin.command"])

    def test_environment_lives_outside_the_checkout(self):
        venv = VARS["gnucash_quick_expense_venv"]
        self.assertFalse(venv.startswith("/opt/gnucash-quick-expense"))
        sync = next(
            t
            for t in tasks_of("app")
            if "uv sync" in str(t.get("ansible.builtin.command", ""))
        )
        self.assertEqual(
            sync["environment"]["UV_PROJECT_ENVIRONMENT"],
            "{{ gnucash_quick_expense_venv }}",
        )


class ServiceTest(unittest.TestCase):
    def test_unit_runs_hardened_on_loopback(self):
        unit = (ROLE / "files" / "gnucash-quick-expense.service").read_text()
        for line in (
            "User=gnucash-quick-expense",
            "NoNewPrivileges=yes",
            "ProtectSystem=strict",
            "ProtectHome=yes",
            "PrivateTmp=yes",
            "OnFailure=failure-notify@%n.service",
            "EnvironmentFile=/etc/gnucash-quick-expense/env",
            "--host 127.0.0.1",
            f"--port {VARS['gnucash_quick_expense_port']}",
        ):
            with self.subTest(line=line):
                self.assertIn(line, unit)

    def test_templates_hold_no_credentials(self):
        for name in ("config.yaml.j2", "gnucash-quick-expense.env.j2"):
            text = (ROLE / "templates" / name).read_text().lower()
            with self.subTest(name=name):
                self.assertNotIn("password", text)
                self.assertNotIn("username", text)

    def test_database_location_needs_no_secret_lookup(self):
        for name in ("host", "port", "name"):
            with self.subTest(name=name):
                value = str(VARS[f"gnucash_quick_expense_db_{name}"])
                self.assertNotIn("lookup(", value)

    def test_config_lists_the_allowed_users(self):
        environment = jinja2.Environment(
            loader=jinja2.FileSystemLoader(ROLE / "templates"),
            undefined=jinja2.StrictUndefined,
        )
        environment.filters["comment"] = lambda text: f"#\n# {text}\n#"
        environment.filters["to_json"] = json.dumps
        text = environment.get_template("config.yaml.j2").render(
            ansible_managed="Ansible managed", **VARS
        )
        self.assertEqual(yaml.safe_load(text)["users"], ["quick-expense"])

    def test_env_requires_tls(self):
        text = (ROLE / "templates" / "gnucash-quick-expense.env.j2").read_text()
        self.assertRegex(text, r"(?m)^GQE_DB_SSLMODE=(require|verify-ca|verify-full)$")


class ApacheTest(unittest.TestCase):
    VHOST = ROLE / "templates" / "expense.rewse.jp.conf.j2"

    def test_vhost_proxies_to_the_loopback_listener(self):
        text = self.VHOST.read_text()
        self.assertIn("ServerName {{ gnucash_quick_expense_hostname }}", text)
        self.assertIn(
            "ProxyPass / http://127.0.0.1:{{ gnucash_quick_expense_port }}/", text
        )
        for header in ("X-Forwarded-For", "X-Forwarded-Host", "X-Real-IP"):
            with self.subTest(header=header):
                self.assertIn(f"RequestHeader unset {header}", text)

    def test_vhost_is_open_to_the_internet(self):
        self.assertNotIn("Require ip", self.VHOST.read_text())


class Fail2banTest(unittest.TestCase):
    # The server answers 401 only when the database rejects the login, so a
    # path the routes would also reach through Apache counts in any spelling.
    REJECTED_PATHS = (
        "/api/accounts",
        "/api/rate",
        "/api/expenses",
        "/api/accounts?x=1",
        "/api/expenses?",
        "//api/rate",
        "/api/%61ccounts",
    )

    def test_jail_reads_the_apache_log(self):
        section = jail(
            ROLE / "templates" / "fail2ban-jail.conf.j2", "gnucash-quick-expense"
        )
        self.assertEqual(section["enabled"], "true")
        self.assertEqual(section["backend"], "auto")
        self.assertEqual(section["filter"], "gnucash-quick-expense")
        self.assertEqual(section["logpath"], "/var/log/apache2/other_vhosts_access.log")
        self.assertIn("apache-deny", section["action"])

    def test_filter_matches_rejected_logins_only(self):
        hostname = VARS["gnucash_quick_expense_hostname"]
        self.assertEqual(hostname, "expense.rewse.jp")
        regex = filter_regex(
            ROLE / "templates" / "fail2ban-filter.conf.j2",
            "gnucash_quick_expense_hostname",
            hostname,
        )
        for path in self.REJECTED_PATHS:
            match = regex.search(access_line(hostname, f"POST {path}", 401))
            with self.subTest(path=path):
                self.assertIsNotNone(match)
                assert match is not None
                self.assertEqual(match["host"], "203.0.113.7")
        for line in (
            access_line(hostname, "POST /api/accounts", 200),
            access_line(hostname, "POST /api/accounts?x=1", 200),
            access_line(hostname, "POST /api/expenses", 400),
            access_line(hostname, "GET / ", 401),
            access_line("nas.rewse.jp", "POST /api/accounts", 401),
        ):
            with self.subTest(line=line):
                self.assertIsNone(regex.search(line))

    @unittest.skipUnless(shutil.which("fail2ban-regex"), "no fail2ban-regex")
    def test_fail2ban_bans_a_rejected_login_in_any_spelling(self):
        hostname = VARS["gnucash_quick_expense_hostname"]
        environment = jinja2.Environment(
            loader=jinja2.FileSystemLoader(ROLE / "templates"),
            undefined=jinja2.StrictUndefined,
        )
        environment.filters["comment"] = lambda text: f"#\n# {text}\n#"
        environment.filters["regex_escape"] = re.escape
        text = environment.get_template("fail2ban-filter.conf.j2").render(
            ansible_managed="Ansible managed",
            gnucash_quick_expense_hostname=hostname,
        )
        lines = [
            access_line(hostname, f"POST {path}", 401) for path in self.REJECTED_PATHS
        ]
        lines.append(access_line(hostname, "POST /api/accounts?x=1", 200))
        log = "".join(
            line.replace("[]", "[10/Nov/2026:12:34:56 +0900]") + "\n" for line in lines
        )
        binary = shutil.which("fail2ban-regex")
        assert binary is not None
        with tempfile.TemporaryDirectory() as tmp:
            filter_path = pathlib.Path(tmp) / "gnucash-quick-expense.conf"
            filter_path.write_text(text)
            log_path = pathlib.Path(tmp) / "test.log"
            log_path.write_text(log)
            result = subprocess.run(
                [binary, "--out", "ip", str(log_path), str(filter_path)],
                capture_output=True,
                text=True,
                check=True,
            )
        self.assertEqual(result.stdout, "203.0.113.7\n" * len(self.REJECTED_PATHS))


if __name__ == "__main__":
    unittest.main()
