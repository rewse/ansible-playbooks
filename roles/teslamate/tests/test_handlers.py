"""Handler contracts for the TeslaMate role."""

import unittest
from pathlib import Path

import yaml

HANDLERS_PATH = Path(__file__).parents[1] / "handlers" / "main.yml"


class RestartHandlerTest(unittest.TestCase):
    """Verify restart handlers apply changed environment files."""

    @classmethod
    def setUpClass(cls):
        with HANDLERS_PATH.open(encoding="utf-8") as handlers_file:
            cls.handlers = {h["name"]: h for h in yaml.safe_load(handlers_file)}

    def test_restart_handlers_recreate_containers(self):
        # docker compose restart keeps the environment a container was
        # created with, so an env_file change needs a recreate.
        for name, service in (
            ("Restart teslamate", "teslamate"),
            ("Restart teslamate-grafana", "teslamate-grafana"),
        ):
            with self.subTest(handler=name):
                compose = self.handlers[name]["community.docker.docker_compose_v2"]
                self.assertEqual(compose["services"], [service])
                self.assertEqual(compose["state"], "present")
                self.assertEqual(compose["recreate"], "always")
                self.assertEqual(compose["pull"], "never")


if __name__ == "__main__":
    unittest.main()
