#!/usr/bin/env python3
"""Contract tests for the filebrowser role."""

import pathlib
import unittest

import jinja2
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROLE = REPO_ROOT / "roles" / "filebrowser"


def render_config() -> dict:
    environment = jinja2.Environment(
        loader=jinja2.FileSystemLoader(ROLE / "templates"),
        undefined=jinja2.StrictUndefined,
    )
    environment.filters["comment"] = lambda text: f"#\n# {text}\n#"
    text = environment.get_template("config.yaml.j2").render(
        ansible_managed="Ansible managed",
        filebrowser_port=8080,
        filebrowser_hostname="nas.rewse.jp",
        filebrowser_sources=[
            {"name": "Home", "path": "/srv/nas/data/homes/tats", "rules": []}
        ],
        admin_user="tats",
        filebrowser_admin_password="pw",
        filebrowser_token_expiration_hours=720,
    )
    return yaml.safe_load(text)


def tasks(name: str) -> dict[str, dict]:
    loaded = yaml.safe_load((ROLE / "tasks" / name).read_text())
    return {task["name"]: task for task in loaded}


class FileBrowserConfigTest(unittest.TestCase):
    def test_http_settings_live_under_http(self):
        config = render_config()
        self.assertEqual(
            config["http"],
            {
                "port": 8080,
                "baseURL": "/",
                "externalUrl": "https://nas.rewse.jp",
                "disableWebDAV": True,
                "trustProxyHeaders": True,
            },
        )
        for key in ("port", "baseURL", "externalUrl", "disableWebDAV"):
            self.assertNotIn(key, config["server"])

    def test_database_is_the_sqlite_file(self):
        self.assertEqual(
            render_config()["server"]["database"],
            {"path": "/home/filebrowser/data/filebrowser.sqlite"},
        )

    def test_template_has_no_migration_source(self):
        self.assertNotIn(
            "migrateFrom", (ROLE / "templates" / "config.yaml.j2").read_text()
        )

    def test_user_defaults_keep_only_account_permissions(self):
        self.assertEqual(
            render_config()["userDefaults"],
            {"account": {"permissions": {"admin": False, "api": False, "share": True}}},
        )

    def test_source_and_auth_are_unchanged(self):
        config = render_config()
        (source,) = config["server"]["sources"]
        self.assertEqual(source["config"]["readOnly"], True)
        self.assertEqual(source["config"]["defaultEnabled"], True)
        self.assertEqual(source["config"]["rules"], [{"ignoreHidden": True}])
        self.assertEqual(config["server"]["cacheDir"], "/home/filebrowser/data/cache")
        self.assertEqual(config["auth"]["methods"]["passkey"]["rpId"], "nas.rewse.jp")
        self.assertEqual(
            config["auth"]["methods"]["passkey"]["rpOrigins"],
            ["https://nas.rewse.jp"],
        )

    def test_signing_key_is_left_to_the_database(self):
        # v2 persists the JWT signing key in SQLite and refuses to start when a
        # configured key differs from it.
        self.assertNotIn("key", render_config()["auth"])
        role_vars = yaml.safe_load((ROLE / "vars" / "main.yml").read_text())
        self.assertNotIn("filebrowser_jwt_secret", role_vars)


class FileBrowserContainerTest(unittest.TestCase):
    def test_v1_migration_is_gone(self):
        imports = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
        self.assertNotIn(
            "database.yml", [t["ansible.builtin.import_tasks"] for t in imports]
        )
        self.assertFalse((ROLE / "tasks" / "database.yml").exists())
        self.assertNotIn("config | Find v1 database", tasks("config.yml"))
        self.assertNotIn(
            "container | Fail when v1 database is not migrated",
            tasks("container.yml"),
        )

    def test_start_waits_until_healthy(self):
        start = tasks("container.yml")["container | Start container"][
            "community.docker.docker_compose_v2"
        ]
        self.assertTrue(start["wait"])
        self.assertEqual(start["wait_timeout"], 300)


if __name__ == "__main__":
    unittest.main()
