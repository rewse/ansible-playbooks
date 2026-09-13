"""Deployment ordering contracts for the TeslaMate role."""

from pathlib import Path
import unittest

import yaml


TASKS_PATH = Path(__file__).parents[1] / "tasks" / "main.yml"


class DeploymentOrderTest(unittest.TestCase):
    """Verify image acquisition fails before deployment state changes."""

    @classmethod
    def setUpClass(cls):
        with TASKS_PATH.open(encoding="utf-8") as tasks_file:
            cls.tasks = yaml.safe_load(tasks_file)
        cls.tasks_by_name = {task["name"]: task for task in cls.tasks}
        cls.task_names = [task["name"] for task in cls.tasks]

    def test_deployment_images_are_staged_before_compose_changes(self):
        pre_pull_name = "teslamate : Pre-pull deployment images"
        compose_name = "teslamate : Add services to compose"
        update_name = "teslamate : Pull and update containers"
        cleanup_name = "teslamate : Remove legacy dashboard patch assets"

        self.assertIn(pre_pull_name, self.tasks_by_name)
        pre_pull = self.tasks_by_name[pre_pull_name]
        self.assertEqual(
            pre_pull["community.docker.docker_image"],
            {"name": "{{ item }}", "source": "pull"},
        )
        self.assertEqual(
            pre_pull["loop"],
            ["{{ teslamate_image_ref }}", "{{ teslamate_grafana_image_ref }}"],
        )
        self.assertIn("not ansible_check_mode", pre_pull["when"])

        self.assertLess(
            self.task_names.index(pre_pull_name), self.task_names.index(compose_name)
        )
        self.assertLess(
            self.task_names.index(compose_name), self.task_names.index(update_name)
        )
        self.assertEqual(
            self.tasks_by_name[update_name]["community.docker.docker_compose_v2"]["pull"],
            "never",
        )
        self.assertLess(
            self.task_names.index(update_name), self.task_names.index(cleanup_name)
        )


if __name__ == "__main__":
    unittest.main()
