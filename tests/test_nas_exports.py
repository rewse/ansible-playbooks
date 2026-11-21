#!/usr/bin/env python3
"""Regression tests for the NFS exports of the NAS backup volume."""

import pathlib
import re
import unittest

import jinja2
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
NAS = REPO_ROOT / "roles" / "nas"


def render_exports(variables: dict) -> str:
    environment = jinja2.Environment(
        loader=jinja2.FileSystemLoader(NAS / "templates"),
        undefined=jinja2.StrictUndefined,
    )
    environment.filters["comment"] = lambda text: f"#\n# {text}\n#"
    template = environment.get_template("exports.j2")
    return template.render(ansible_managed="Ansible managed", **variables)


class ExportsTest(unittest.TestCase):
    def setUp(self):
        self.variables = yaml.safe_load((NAS / "vars" / "main.yml").read_text())
        self.backup_path = self.variables["nas_backup_path"]

    def exports(self) -> list[tuple[str, str, list[str]]]:
        lines = [
            line
            for line in render_exports(self.variables).splitlines()
            if line and not line.startswith("#")
        ]
        exports = []
        for line in lines:
            match = re.fullmatch(r"(\S+) ([^\s(]+)\(([^)]*)\)", line)
            self.assertIsNotNone(match, line)
            assert match is not None
            exports.append((match[1], match[2], match[3].split(",")))
        return exports

    def test_backup_path_is_the_backup_volume_mount_point(self):
        mount_points = [
            volume["path"].replace("{{ nas_backup_path }}", self.backup_path)
            for volume in self.variables["nas_volumes"]
        ]
        self.assertIn(self.backup_path, mount_points)

    def test_every_export_requires_the_backup_volume_mounted(self):
        exports = self.exports()
        self.assertEqual(len(exports), len(self.variables["nas_nfs_clients"]))
        for path, _, options in exports:
            self.assertTrue(path.startswith(self.backup_path + "/"), path)
            self.assertIn(f"mp={self.backup_path}", options, path)

    def test_every_export_checks_its_subtree(self):
        exports = self.exports()
        self.assertTrue(exports)
        for path, _, options in exports:
            self.assertIn("subtree_check", options, path)
            self.assertNotIn("no_subtree_check", options, path)

    def test_each_client_gets_only_its_own_directory(self):
        self.assertEqual(
            [(path, address) for path, address, _ in self.exports()],
            [
                (f"{self.backup_path}/{client['name']}", client["address"])
                for client in self.variables["nas_nfs_clients"]
            ],
        )


if __name__ == "__main__":
    unittest.main()
