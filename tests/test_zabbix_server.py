#!/usr/bin/env python3
"""Regression tests for how the zabbix_server role connects to PostgreSQL."""

import pathlib
import re
import unittest

import jinja2
import yaml

ROLES = pathlib.Path(__file__).resolve().parents[1] / "roles"
ROLE = ROLES / "zabbix_server"
CA_FILE = "/etc/zabbix/aws-rds-global-bundle.pem"


def load_yaml(path: pathlib.Path):
    return yaml.safe_load(path.read_text())


def tasks_by_name(path: pathlib.Path) -> dict:
    return {task["name"]: task for task in load_yaml(path)}


def php_setting(text: str, key: str) -> str:
    match = re.search(rf"^\$DB\['{key}'\]\s*=\s*(.+?);\s*$", text, re.MULTILINE)
    if match is None:
        raise AssertionError(f"$DB['{key}'] is not set")
    return match.group(1)


class DatabaseTlsTest(unittest.TestCase):
    """Both the frontend and the server authenticate the Aurora certificate."""

    @classmethod
    def setUpClass(cls):
        cls.vars = load_yaml(ROLE / "vars" / "main.yml")
        cls.teslamate_vars = load_yaml(ROLES / "teslamate" / "vars" / "main.yml")

    def test_ca_bundle_is_pinned_like_teslamate(self):
        # Both roles download the same RDS bundle onto fox, so they pin the
        # same content.
        self.assertEqual(
            self.vars["zabbix_server_db_ca_url"],
            self.teslamate_vars["teslamate_database_ca_url"],
        )
        self.assertEqual(
            self.vars["zabbix_server_db_ca_checksum"],
            self.teslamate_vars["teslamate_database_ca_checksum"],
        )
        self.assertEqual(self.vars["zabbix_server_db_ca_file"], CA_FILE)

    def test_db_host_is_the_name_in_the_certificate(self):
        # The certificate names the cluster endpoint, not a CNAME pointing at
        # it, so host verification fails for any other name.
        self.assertEqual(
            self.vars["zabbix_server_db_host"],
            self.teslamate_vars["teslamate_database_tls_host"],
        )

    def test_ca_bundle_is_downloaded_by_each_component(self):
        # Each component runs alone under its tag, so each one fetches the
        # bundle it points at.
        for component in ("frontend", "server"):
            with self.subTest(component=component):
                tasks = tasks_by_name(ROLE / "tasks" / f"{component}.yml")
                task = tasks[f"{component} | Download Amazon RDS CA bundle"]
                get_url = task["ansible.builtin.get_url"]
                self.assertEqual(get_url["url"], "{{ zabbix_server_db_ca_url }}")
                self.assertEqual(get_url["dest"], "{{ zabbix_server_db_ca_file }}")
                self.assertEqual(
                    get_url["checksum"], "{{ zabbix_server_db_ca_checksum }}"
                )
                # www-data and zabbix both read it.
                self.assertEqual(get_url["mode"], "0644")
                names = list(tasks)
                consumer = {
                    "frontend": "frontend | Copy PHP config",
                    "server": "server | Set DBTLSCAFile",
                }[component]
                self.assertLess(names.index(task["name"]), names.index(consumer))

    def test_server_verifies_the_certificate_and_host(self):
        tasks = tasks_by_name(ROLE / "tasks" / "server.yml")
        expected = {
            "server | Set DBTLSCAFile": "DBTLSCAFile={{ zabbix_server_db_ca_file }}",
            "server | Set DBTLSConnect": "DBTLSConnect=verify_full",
        }
        for name, line in expected.items():
            with self.subTest(name=name):
                lineinfile = tasks[name]["ansible.builtin.lineinfile"]
                self.assertEqual(lineinfile["dest"], "/etc/zabbix/zabbix_server.conf")
                self.assertEqual(lineinfile["line"], line)
                key = line.split("=", 1)[0]
                self.assertEqual(lineinfile["regexp"], f"^{key}=")
                self.assertEqual(tasks[name]["notify"], "Restart zabbix-server")

    def test_frontend_verifies_the_certificate_and_host(self):
        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(ROLE / "templates"),
            undefined=jinja2.StrictUndefined,
            keep_trailing_newline=True,
        )
        text = env.get_template("zabbix.conf.php.j2").render(
            zabbix_server_db_ca_file=CA_FILE,
            zabbix_server_db_host="database.cluster.example.test",
            zabbix_server_db_password="DUMMY_PASSWORD",
        )
        self.assertEqual(php_setting(text, "SERVER"), "'database.cluster.example.test'")
        self.assertEqual(php_setting(text, "ENCRYPTION"), "true")
        # With a CA file set, the frontend connects with sslmode verify-full
        # when VERIFY_HOST is true and verify-ca otherwise.
        self.assertEqual(php_setting(text, "CA_FILE"), f"'{CA_FILE}'")
        self.assertEqual(php_setting(text, "VERIFY_HOST"), "true")


if __name__ == "__main__":
    unittest.main()
