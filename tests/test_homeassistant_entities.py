#!/usr/bin/env python3
"""Regression tests for entity IDs the Home Assistant configuration refers to."""

import pathlib
import re
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
FILES = REPO_ROOT / "roles" / "homeassistant" / "files"

# The manual panels in alarm_control_panels.yaml, as registered in the live
# instance. Their entity IDs are kept in the registry, not derived from a file.
ALARM_PANELS = {"alarm_control_panel.entrance", "alarm_control_panel.home"}
# alarm_control_panel.alarm_* are actions, not entities.
ALARM_PANEL_REFERENCE = re.compile(r"\balarm_control_panel\.(?!alarm_)[a-z0-9_]+")


class AlarmPanelReferenceTest(unittest.TestCase):
    def test_only_existing_alarm_panels_are_referenced(self):
        for path in sorted(FILES.glob("*.yaml")):
            if path.name == "alarm_control_panels.yaml":
                continue
            for entity in ALARM_PANEL_REFERENCE.findall(path.read_text()):
                with self.subTest(file=path.name, entity=entity):
                    self.assertIn(entity, ALARM_PANELS)


if __name__ == "__main__":
    unittest.main()
