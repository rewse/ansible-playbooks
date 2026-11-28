#!/usr/bin/env python3
"""Contract tests for the rex role."""

import pathlib
import unittest

import jinja2
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROLE = REPO_ROOT / "roles" / "rex"


def role_vars() -> dict:
    return yaml.safe_load((ROLE / "vars" / "main.yml").read_text())


def task(file: str, name: str) -> dict:
    tasks = yaml.safe_load((ROLE / "tasks" / file).read_text())
    return next(t for t in tasks if t["name"] == name)


def render_preferences() -> str:
    environment = jinja2.Environment(
        loader=jinja2.FileSystemLoader(ROLE / "templates"),
        undefined=jinja2.StrictUndefined,
        keep_trailing_newline=True,
    )
    environment.filters["comment"] = lambda text: f"#\n# {text}\n#"
    return environment.get_template("preferences.j2").render(
        ansible_managed="Ansible managed", **role_vars()
    )


class AptTest(unittest.TestCase):
    def test_channel_is_preview_until_stable_exists(self):
        self.assertEqual(role_vars()["rex_apt_channel"], "preview")

    def test_architectures_use_dpkg_names(self):
        self.assertEqual(
            role_vars()["rex_apt_architectures"],
            {"aarch64": "arm64", "x86_64": "amd64"},
        )

    # Ubuntu ships an unrelated package named rex. The second record keeps
    # unattended-upgrades from installing it, and only works after the first.
    def test_pin_prefers_rex_and_bans_every_other_rex(self):
        blocks = [
            [line for line in block.splitlines() if line and not line.startswith("#")]
            for block in render_preferences().split("\n\n")
        ]
        records = [
            dict(line.split(": ", 1) for line in block) for block in blocks if block
        ]
        self.assertEqual(
            records,
            [
                {
                    "Package": "rex",
                    "Pin": "origin pkgs.superlogical.com",
                    "Pin-Priority": "1001",
                },
                {"Package": "rex", "Pin": "release *", "Pin-Priority": "-1"},
            ],
        )

    def test_repository_trusts_the_rex_key_only(self):
        repo = task("apt.yml", "apt | Add apt repository")[
            "ansible.builtin.deb822_repository"
        ]
        self.assertEqual(repo["name"], "rex")
        self.assertEqual(repo["uris"], "{{ rex_apt_uri }}")
        self.assertEqual(repo["suites"], "{{ rex_apt_channel }}")
        self.assertEqual(repo["components"], "main")
        self.assertEqual(repo["signed_by"], "{{ rex_apt_keyring }}")
        self.assertEqual(
            repo["architectures"],
            "{{ rex_apt_architectures[ansible_facts['architecture']] }}",
        )
        self.assertEqual(
            role_vars()["rex_apt_keyring"], "/etc/apt/keyrings/rex-archive-keyring.gpg"
        )
        self.assertEqual(
            role_vars()["rex_apt_uri"], "https://pkgs.superlogical.com/rex/apt"
        )

    def test_pin_is_in_place_before_rex_is_installed(self):
        names = [
            t["name"] for t in yaml.safe_load((ROLE / "tasks" / "apt.yml").read_text())
        ]
        self.assertLess(
            names.index("apt | Pin rex to the Rex repository"),
            names.index("apt | Install rex"),
        )
        pin = task("apt.yml", "apt | Pin rex to the Rex repository")[
            "ansible.builtin.template"
        ]
        self.assertEqual(
            (pin["src"], pin["dest"], pin["mode"]),
            ("preferences.j2", "/etc/apt/preferences.d/rex", "0644"),
        )

    def test_role_runs_on_fox_with_its_tag(self):
        play = yaml.safe_load((REPO_ROOT / "home-primary.yml").read_text())[0]
        roles = [r["role"] for r in play["roles"]]
        self.assertEqual(roles[roles.index("nvr") + 1], "rex")
        self.assertEqual(play["roles"][roles.index("rex")]["tags"], ["rex"])


class ServerTest(unittest.TestCase):
    RUNTIME_DIR = "/run/user/{{ ansible_facts['getent_passwd'][admin_user][1] }}"

    def test_linger_comes_before_the_socket_is_enabled(self):
        names = [
            t["name"]
            for t in yaml.safe_load((ROLE / "tasks" / "server.yml").read_text())
        ]
        self.assertLess(
            names.index("server | Enable linger for admin"),
            names.index("server | Enable socket"),
        )
        linger = task("server.yml", "server | Enable linger for admin")
        self.assertEqual(
            linger["ansible.builtin.command"]["cmd"],
            "loginctl enable-linger {{ admin_user }}",
        )
        self.assertIn("changed_when", linger)

    # changed_when overrides a creates skip, so the task must not run at all
    # once lingering is on, or every run reports a change.
    def test_linger_runs_only_while_it_is_off(self):
        check = task("server.yml", "server | Check linger for admin")
        self.assertEqual(
            check["ansible.builtin.stat"]["path"],
            "/var/lib/systemd/linger/{{ admin_user }}",
        )
        self.assertEqual(check["register"], "__rex_server_linger")
        linger = task("server.yml", "server | Enable linger for admin")
        self.assertEqual(linger["when"], "not __rex_server_linger.stat.exists")
        self.assertNotIn("creates", linger["ansible.builtin.command"])

    # rex.socket is the unit `rex server install` enables for the packaged rex.
    def test_admin_socket_starts_the_server_on_demand(self):
        start = task("server.yml", "server | Enable socket")
        unit = start["ansible.builtin.systemd_service"]
        self.assertEqual(
            (unit["name"], unit["scope"], unit["state"], unit["enabled"]),
            ("rex.socket", "user", "started", True),
        )
        self.assertEqual(start["become_user"], "{{ admin_user }}")

    def test_user_scope_tasks_reach_the_user_manager(self):
        start = task("server.yml", "server | Enable socket")
        self.assertEqual(start["environment"]["XDG_RUNTIME_DIR"], self.RUNTIME_DIR)

    def test_socket_task_skips_in_check_mode_before_install(self):
        unit = task("server.yml", "server | Check socket unit")
        self.assertEqual(
            unit["ansible.builtin.stat"]["path"], "/usr/lib/systemd/user/rex.socket"
        )
        self.assertEqual(unit["register"], "__rex_server_unit")
        runtime = task("server.yml", "server | Check admin runtime directory")
        self.assertEqual(runtime["ansible.builtin.stat"]["path"], self.RUNTIME_DIR)
        self.assertEqual(runtime["register"], "__rex_server_runtime")
        self.assertEqual(
            task("server.yml", "server | Enable socket")["when"],
            "not ansible_check_mode or"
            " (__rex_server_unit.stat.exists and __rex_server_runtime.stat.exists)",
        )

    def test_server_is_imported_with_its_tag(self):
        imports = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
        self.assertEqual(
            [(t["ansible.builtin.import_tasks"], t["tags"]) for t in imports],
            [("apt.yml", ["rex_apt"]), ("server.yml", ["rex_server"])],
        )


if __name__ == "__main__":
    unittest.main()
