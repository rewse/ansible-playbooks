#!/usr/bin/env python3
"""Regression tests for the enecoQ data fetcher role."""

import pathlib
import unittest
from typing import Any

import yaml

ROLE = pathlib.Path(__file__).resolve().parents[1] / "roles" / "enecoq_data_fetcher"
TOGGLE = "enecoq_data_fetcher_timer_enabled"


def load(path: str) -> Any:
    return yaml.safe_load((ROLE / path).read_text())


def named(path: str, name: str) -> dict[str, Any]:
    (entry,) = [e for e in load(path) if e["name"] == name]
    return entry


class TimerToggleTest(unittest.TestCase):
    # One variable decides whether the timer runs, so a change to the timer unit
    # cannot start a timer that the variable keeps off.
    def test_toggle_is_a_boolean(self):
        self.assertIsInstance(load("vars/main.yml")[TOGGLE], bool)

    def test_timer_follows_the_toggle(self):
        task = named("tasks/service.yml", "service | Enable and start timer")
        systemd = task["ansible.builtin.systemd"]
        self.assertEqual(systemd["enabled"], "{{ " + TOGGLE + " }}")
        self.assertEqual(
            systemd["state"], "{{ 'started' if " + TOGGLE + " else 'stopped' }}"
        )

    def test_restart_handler_follows_the_toggle(self):
        handler = named("handlers/main.yml", "Restart enecoq-data-fetcher timer")
        self.assertEqual(handler.get("when"), TOGGLE)


if __name__ == "__main__":
    unittest.main()
