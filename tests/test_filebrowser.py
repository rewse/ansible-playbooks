#!/usr/bin/env python3
"""Contract tests for the filebrowser role."""

import pathlib
import unittest

import jinja2
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROLE = REPO_ROOT / "roles" / "filebrowser"


def render_config(matched: int) -> dict:
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
        filebrowser_jwt_secret="key",
        filebrowser_token_expiration_hours=720,
        __filebrowser_boltdb_files={"matched": matched},
    )
    return yaml.safe_load(text)


def tasks(name: str) -> dict[str, dict]:
    loaded = yaml.safe_load((ROLE / "tasks" / name).read_text())
    return {task["name"]: task for task in loaded}


class FileBrowserConfigTest(unittest.TestCase):
    def test_http_settings_live_under_http(self):
        config = render_config(0)
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

    def test_database_has_no_migration_source_without_v1_database(self):
        self.assertEqual(
            render_config(0)["server"]["database"],
            {"path": "/home/filebrowser/data/filebrowser.sqlite"},
        )

    def test_database_migrates_while_v1_database_remains(self):
        self.assertEqual(
            render_config(1)["server"]["database"],
            {
                "path": "/home/filebrowser/data/filebrowser.sqlite",
                "migrateFrom": "/home/filebrowser/data/database.db.old",
            },
        )

    def test_user_defaults_keep_only_account_permissions(self):
        self.assertEqual(
            render_config(0)["userDefaults"],
            {"account": {"permissions": {"admin": False, "api": False, "share": True}}},
        )

    def test_source_and_auth_are_unchanged(self):
        config = render_config(0)
        (source,) = config["server"]["sources"]
        self.assertEqual(source["config"]["readOnly"], True)
        self.assertEqual(source["config"]["defaultEnabled"], True)
        self.assertEqual(source["config"]["rules"], [{"ignoreHidden": True}])
        self.assertEqual(config["server"]["cacheDir"], "/home/filebrowser/data/cache")
        self.assertEqual(
            config["auth"]["methods"]["passkey"]["rpId"], "nas.rewse.jp"
        )
        self.assertEqual(
            config["auth"]["methods"]["passkey"]["rpOrigins"],
            ["https://nas.rewse.jp"],
        )

    def test_config_task_finds_v1_database_before_rendering(self):
        config = tasks("config.yml")
        names = list(config)
        find = config["config | Find v1 database"]["ansible.builtin.find"]
        self.assertEqual(find["patterns"], ["database.db", "database.db.old"])
        self.assertEqual(
            config["config | Find v1 database"]["register"],
            "__filebrowser_boltdb_files",
        )
        self.assertLess(
            names.index("config | Find v1 database"),
            names.index("config | Deploy configuration file"),
        )


if __name__ == "__main__":
    unittest.main()
