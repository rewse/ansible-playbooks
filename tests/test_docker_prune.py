#!/usr/bin/env python3
"""Contract tests for the prune component of the docker role."""

import pathlib
import unittest

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROLE = REPO_ROOT / "roles" / "docker"


def load_tasks(name: str) -> list[dict]:
    return yaml.safe_load((ROLE / "tasks" / name).read_text())


class PruneTest(unittest.TestCase):
    def test_prune_touches_only_images_and_build_cache(self):
        # Pruning containers or volumes would delete the stopped standby
        # container on the secondary and service data.
        tasks = load_tasks("prune.yml")
        self.assertEqual(len(tasks), 1)
        self.assertEqual(
            tasks[0]["name"], "prune | Remove unused images and build cache"
        )
        self.assertEqual(
            tasks[0]["community.docker.docker_prune"],
            {
                "builder_cache": True,
                "builder_cache_all": True,
                "images": True,
                "images_filters": {"dangling": False},
                "timeout": 600,
            },
        )

    def test_main_imports_prune_last_with_update_tag(self):
        # The update tag makes `--tags update` runs clear the generation they
        # replaced on the previous run.
        last = load_tasks("main.yml")[-1]
        self.assertEqual(last["ansible.builtin.import_tasks"], "prune.yml")
        self.assertEqual(last["tags"], ["docker_prune", "update"])


if __name__ == "__main__":
    unittest.main()
