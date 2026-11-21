#!/usr/bin/env python3
"""Regression tests for the Home Assistant alarm automations."""

import pathlib
import unittest

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
FILES = REPO_ROOT / "roles" / "homeassistant" / "files"


def load_automations(name):
    return {
        automation["id"]: automation
        for automation in yaml.safe_load((FILES / name).read_text())
    }


class CameraPlugUnavailableTest(unittest.TestCase):
    """Sync Frigate Cameras disables a camera whose plug is not on, so an
    unavailable plug stops recording and must reach the owner."""

    def setUp(self):
        self.alarm = load_automations("automations-alarm.yaml")[
            "automation.alarm_camera_plug_unavailable"
        ]
        sync = load_automations("automations-securities.yaml")[
            "automation.sync_frigate_cameras"
        ]
        self.camera_plugs = {
            entity
            for trigger in sync["triggers"]
            if trigger["trigger"] == "state"
            for entity in trigger["entity_id"]
        }

    def test_every_camera_plug_triggers_after_five_minutes_unavailable(self):
        triggers = [
            trigger
            for trigger in self.alarm["triggers"]
            if trigger["trigger"] == "state"
            and trigger.get("to") == "unavailable"
            and trigger.get("for") == {"minutes": 5}
        ]
        covered = {entity for trigger in triggers for entity in trigger["entity_id"]}
        self.assertTrue(self.camera_plugs)
        self.assertEqual(covered, self.camera_plugs)

    def test_owner_gets_a_time_sensitive_push(self):
        notify = [
            action
            for action in self.alarm["actions"]
            if action.get("action") == "notify.tats_devices"
        ]
        self.assertEqual(len(notify), 1)
        data = notify[0]["data"]
        self.assertIn("recording", data["message"].lower())
        self.assertEqual(data["data"]["push"]["interruption-level"], "time-sensitive")


if __name__ == "__main__":
    unittest.main()
