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


class FileBrowserMigrationTest(unittest.TestCase):
    def test_database_component_runs_before_config(self):
        imports = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
        files = [task["ansible.builtin.import_tasks"] for task in imports]
        self.assertLess(files.index("database.yml"), files.index("config.yml"))
        (database,) = [
            t for t in imports if t["ansible.builtin.import_tasks"] == "database.yml"
        ]
        self.assertEqual(database["tags"], ["filebrowser_database"])

    def test_v1_database_is_stopped_backed_up_and_renamed_only_when_present(self):
        database = tasks("database.yml")
        stop = database["database | Stop container"]
        self.assertEqual(stop["community.docker.docker_compose_v2"]["state"], "stopped")
        self.assertIn("__filebrowser_compose_file.stat.exists", stop["when"])
        backup = database["database | Back up v1 database"]["ansible.builtin.copy"]
        self.assertTrue(backup["remote_src"])
        self.assertEqual(backup["dest"], "/var/backups/filebrowser/database.db")
        self.assertEqual(backup["mode"], "0600")
        rename = database["database | Rename v1 database for migration"]
        self.assertEqual(
            rename["args"]["removes"], "{{ filebrowser_data_dir }}/database.db"
        )
        self.assertEqual(
            rename["args"]["creates"], "{{ filebrowser_data_dir }}/database.db.old"
        )
        self.assertIn("changed_when", rename)
        for name in ("database | Stop container", "database | Back up v1 database"):
            self.assertIn("__filebrowser_boltdb.stat.exists", database[name]["when"])

    def test_container_refuses_an_unmigrated_database_outside_check_mode(self):
        container = tasks("container.yml")
        names = list(container)
        guard = container["container | Fail when v1 database is not migrated"]
        self.assertIn("__filebrowser_boltdb_left.stat.exists", guard["when"])
        self.assertIn("not ansible_check_mode", guard["when"])
        self.assertLess(
            names.index("container | Fail when v1 database is not migrated"),
            names.index("container | Start container"),
        )

    def test_start_waits_until_healthy(self):
        start = tasks("container.yml")["container | Start container"][
            "community.docker.docker_compose_v2"
        ]
        self.assertTrue(start["wait"])
        self.assertEqual(start["wait_timeout"], 300)


if __name__ == "__main__":
    unittest.main()
