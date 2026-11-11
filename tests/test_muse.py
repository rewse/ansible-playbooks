"""Regression tests for the muse role."""

import pathlib
import unittest

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROLE = REPO_ROOT / "roles" / "muse"


class PgpassTest(unittest.TestCase):
    def test_pgpass_targets_only_rewse_pg(self):
        variables = yaml.safe_load((ROLE / "vars" / "main.yml").read_text())
        hosts = [entry["host"] for entry in variables["muse_pgpass_entries"]]
        self.assertEqual(hosts, ["rewse-pg.rewse.jp"])


if __name__ == "__main__":
    unittest.main()
