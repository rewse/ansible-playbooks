#!/usr/bin/env python3
"""Regression tests for entity IDs the Home Assistant configuration refers to."""

import pathlib
import re
import unittest

import yaml

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


class HomeKitNameTest(unittest.TestCase):
    def test_every_included_entity_has_a_unique_name(self):
        (bridge,) = yaml.safe_load((FILES / "homekit.yaml").read_text())
        entity_config = bridge.get("entity_config", {})
        names = []
        for entity in bridge["filter"]["include_entities"]:
            with self.subTest(entity=entity):
                name = entity_config.get(entity, {}).get("name")
                self.assertTrue(name)
                # Accessory names use the ASCII apostrophe.
                self.assertNotIn("\u2019", name)
                names.append(name)
        self.assertEqual(len(names), len(set(names)))


class SceneOptionTest(unittest.TestCase):
    # Hue provides the light group scenes; scenes.yaml defines the others.
    HUE_SCENE = re.compile(r"^scene\.[a-z0-9_]+_light_group_[a-z0-9_]+$")

    def test_every_scene_option_is_defined(self):
        defined = {
            scene["id"] for scene in yaml.safe_load((FILES / "scenes.yaml").read_text())
        }
        input_selects = yaml.safe_load((FILES / "input_selects.yaml").read_text())
        for key, config in input_selects.items():
            for option in config["options"]:
                if not option.startswith("scene.") or self.HUE_SCENE.match(option):
                    continue
                with self.subTest(input_select=key, scene=option):
                    self.assertIn(option, defined)


if __name__ == "__main__":
    unittest.main()
