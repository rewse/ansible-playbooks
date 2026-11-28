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
        records = [dict(line.split(": ", 1) for line in block) for block in blocks if block]
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


if __name__ == "__main__":
    unittest.main()
