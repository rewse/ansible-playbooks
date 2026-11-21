#!/usr/bin/env python3
"""Contract tests for the filebrowser role."""

import pathlib
import re
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


def second_policy() -> dict[str, list[str]]:
    """Returns the directives of the policy the vhost adds to FileBrowser's."""
    environment = jinja2.Environment(
        loader=jinja2.FileSystemLoader(ROLE / "templates"),
        undefined=jinja2.StrictUndefined,
    )
    environment.filters["comment"] = lambda text: f"#\n# {text}\n#"
    text = environment.get_template("nas.rewse.jp.conf.j2").render(
        ansible_managed="Ansible managed",
        filebrowser_hostname="nas.rewse.jp",
        filebrowser_port=8080,
    )
    (line,) = [
        line.strip()
        for line in text.splitlines()
        if line.strip().startswith("Header always set Content-Security-Policy ")
    ]
    (policy,) = re.findall(r'"([^"]*)"', line)
    return {
        part.split()[0]: part.split()[1:]
        for part in (piece.strip() for piece in policy.split(";"))
        if part
    }


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

    def test_source_and_passkey_settings_are_kept(self):
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


class FileBrowserSecondPolicyTest(unittest.TestCase):
    # Fetch directives that fall back to default-src.
    FETCH_DIRECTIVES = (
        "connect-src",
        "default-src",
        "font-src",
        "frame-src",
        "img-src",
        "manifest-src",
        "media-src",
        "script-src",
        "style-src",
        "worker-src",
    )

    @classmethod
    def setUpClass(cls):
        cls.policy = second_policy()

    def test_default_src_keeps_other_fetches_on_the_origin(self):
        # Prefetch and any other request without its own directive, from the
        # app or from a document previewed in a srcdoc frame, falls back here.
        self.assertEqual(self.policy["default-src"], ["'self'", "blob:", "data:"])

    def test_fetch_directives_name_no_other_origin(self):
        local = {"'none'", "'self'", "'unsafe-inline'", "blob:", "data:"}
        for directive in self.FETCH_DIRECTIVES:
            with self.subTest(directive=directive):
                self.assertIn(directive, self.policy)
                self.assertLessEqual(set(self.policy[directive]), local)

    def test_script_src_is_no_stricter_than_the_app_policy(self):
        # The app's own policy allows 'self' and its per-page nonce. Both
        # policies are enforced, so this one has to allow the nonce scripts.
        # 'unsafe-inline' does that only while the policy names no nonce, hash
        # or 'strict-dynamic', each of which would make browsers ignore it.
        script_src = self.policy["script-src"]
        self.assertEqual(script_src, ["'self'", "'unsafe-inline'"])

    def test_app_requests_stay_allowed(self):
        # The API and the file watcher's EventSource, the editor's blob
        # worker, the web manifest, and blob or data URLs that viewers build.
        self.assertEqual(self.policy["connect-src"], ["'self'", "blob:", "data:"])
        self.assertEqual(self.policy["manifest-src"], ["'self'"])
        self.assertEqual(self.policy["worker-src"], ["'self'", "blob:"])
        self.assertEqual(self.policy["font-src"], ["'self'", "blob:", "data:"])


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
