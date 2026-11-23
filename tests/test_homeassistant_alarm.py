#!/usr/bin/env python3
"""Regression tests for the Home Assistant alarm automations."""

import pathlib
import unittest

import jinja2
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
            "automation.alarm_camera_plug_is_unavailable"
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


def iter_messages(actions):
    for action in actions:
        message = action.get("data", {}).get("message")
        if isinstance(message, str):
            yield message


class NotificationDisplayNameTest(unittest.TestCase):
    """Alarm notifications name the triggering entity from its area, device,
    and entity names, because friendly_name omits parts of the name."""

    NAMED_AUTOMATIONS = (
        "automation.alarm_armed_vacation_windows",
        "automation.alarm_camera_plug_is_unavailable",
        "automation.alarm_device_battery_level",
        "automation.alarm_device_offline",
        "automation.alarm_matter_sensor_is_offline",
    )

    CASES = (
        # (area, device, entity, expected prefix of the message)
        (
            "Living Room",
            "Thermometer",
            "Temperature",
            "Living Room Thermometer Temperature",
        ),
        # Main entity
        ("Living Room", "Humidifier Plug", "", "Living Room Humidifier Plug"),
        # Area still in device name
        (
            "Living Room",
            "Living Room Thermometer",
            "Temperature",
            "Living Room Thermometer Temperature",
        ),
        # No device, area in name
        (
            "Living Room",
            None,
            "Living Room Thermometer Fault",
            "Living Room Thermometer Fault",
        ),
        # No device, area removed
        ("Living Room", None, "Thermometer Fault", "Living Room Thermometer Fault"),
        # Nothing known: object ID
        (None, None, None, "living_room_unknown"),
    )

    def setUp(self):
        self.automations = load_automations("automations-alarm.yaml")
        self.environment = jinja2.Environment()

    def render(self, message, area, device, entity):
        entity_id = "binary_sensor.living_room_unknown"
        names = {
            "area_name": area,
            "device_name": device,
            "entity_name": entity,
        }
        functions = {
            key: (
                lambda lookup_id, value=value: value if lookup_id == entity_id else None
            )
            for key, value in names.items()
        }
        trigger = {"entity_id": entity_id, "to_state": {"state": "10"}}
        return self.environment.from_string(message).render(
            trigger=trigger, **functions
        )

    def test_no_message_uses_friendly_name(self):
        for automation in self.automations.values():
            for message in iter_messages(automation["actions"]):
                self.assertNotIn("friendly_name", message, automation["id"])

    def test_message_names_the_entity(self):
        for automation_id in self.NAMED_AUTOMATIONS:
            messages = list(iter_messages(self.automations[automation_id]["actions"]))
            self.assertEqual(len(messages), 1, automation_id)
            for area, device, entity, expected in self.CASES:
                with self.subTest(automation=automation_id, case=expected):
                    rendered = self.render(messages[0], area, device, entity)
                    self.assertTrue(
                        rendered.startswith((expected + " ", expected + "’")),
                        rendered,
                    )


if __name__ == "__main__":
    unittest.main()
