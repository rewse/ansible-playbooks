"""Tests for the Home Assistant naming migration tool."""

import pathlib
import sys
import tempfile
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.homeassistant_rename.rules import expand_abbreviations
from tools.homeassistant_rename.rules import in_scope
from tools.homeassistant_rename.rules import normalize_apostrophe
from tools.homeassistant_rename.rules import normalize_modifiers
from tools.homeassistant_rename.rules import strip_area
from tools.homeassistant_rename.snapshot import Snapshot


def sample_snapshot() -> Snapshot:
    return Snapshot(
        areas=[{"area_id": "living_room", "name": "Living Room"}],
        devices=[
            {
                "area_id": "living_room",
                "id": "d1",
                "name": "Hue Bulb",
                "name_by_user": None,
            }
        ],
        entities=[
            {
                "device_id": "d1",
                "entity_id": "light.living_room_bulb",
                "name": None,
                "original_name": None,
            }
        ],
        states={
            "light.living_room_bulb": {
                "attributes": {"friendly_name": "Living Room Bulb"},
                "entity_id": "light.living_room_bulb",
                "state": "on",
            }
        },
    )


class SnapshotTest(unittest.TestCase):
    def test_round_trip(self):
        snapshot = sample_snapshot()
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "snapshot.json"
            snapshot.save(path)
            self.assertEqual(Snapshot.load(path), snapshot)

    def test_states_are_keyed_by_entity_id(self):
        states = [
            {"entity_id": "light.a", "state": "on"},
            {"entity_id": "sensor.b", "state": "21.5"},
        ]
        snapshot = Snapshot.from_lists(areas=[], devices=[], entities=[], states=states)
        self.assertEqual(sorted(snapshot.states), ["light.a", "sensor.b"])
        self.assertEqual(snapshot.states["sensor.b"]["state"], "21.5")


AREA_NAMES = ["Dad’s Room", "Living Room"]

STRIP_AREA = [
    ("Living Room Thermometer", "Thermometer"),
    ("Dad’s Room AC", "AC"),
    ("Dad's Room AC", "AC"),
    ("Living Room", ""),  # Hue room group: needs a new name
    ("Thermometer", "Thermometer"),
]
MODIFIERS = [
    ("Window Sensor N", ("Window Sensor North", False)),
    ("Presence Sensor E", ("Presence Sensor East", False)),
    ("Left Light", ("Light Left", False)),
    ("Center Plug", ("Plug Center", False)),
    ("Study Floor Heater", ("Floor Heater North", False)),
    ("Study Downlights", ("Downlights North", False)),
    ("Floor Heater 2", ("Floor Heater 2", True)),  # numbered: review
    ("Plug East", ("Plug East", False)),
]
ABBREVIATIONS = [
    (
        "living_room_temp_max_diff_present_summer_midnight",
        "living_room_temperature_maximum_difference_present_summer_midnight",
    ),
    ("dads_room_humidity_min_diff", "dads_room_humidity_minimum_difference"),
    ("living_room_ac_temperature", "living_room_ac_temperature"),
    ("living_room_tv_plug", "living_room_tv_plug"),
    ("moms_room_air_purifier_pm2_5", "moms_room_air_purifier_pm2_5"),
    ("template_x", "template_x"),  # "temp" only as a whole token
]


def registry_entity(
    entity_id: str, platform: str, device_id: str | None = None
) -> dict:
    return {
        "area_id": None,
        "device_id": device_id,
        "entity_id": entity_id,
        "platform": platform,
    }


def registry_device(area_id: str | None) -> dict:
    return {"area_id": area_id, "id": "d1", "identifiers": [["hue", "x"]]}


class RulesTest(unittest.TestCase):
    def test_normalize_apostrophe(self):
        self.assertEqual(normalize_apostrophe("Dad’s Room"), "Dad's Room")
        self.assertEqual(normalize_apostrophe("Mom's Room"), "Mom's Room")

    def test_strip_area(self):
        for name, expected in STRIP_AREA:
            with self.subTest(name=name):
                self.assertEqual(strip_area(name, AREA_NAMES), expected)

    def test_normalize_modifiers(self):
        for name, expected in MODIFIERS:
            with self.subTest(name=name):
                self.assertEqual(normalize_modifiers(name), expected)

    def test_expand_abbreviations(self):
        for object_id, expected in ABBREVIATIONS:
            with self.subTest(object_id=object_id):
                self.assertEqual(expand_abbreviations(object_id), expected)

    def test_in_scope_excludes(self):
        cases = [
            (
                "device without area",
                registry_device(None),
                registry_entity("light.a", "hue", "d1"),
                None,
            ),
            (
                "person without area",
                None,
                registry_entity("person.tats", "person"),
                None,
            ),
            (
                "device_tracker without area",
                None,
                registry_entity("device_tracker.phone", "mobile_app"),
                None,
            ),
            (
                "unifi device",
                registry_device("living_room"),
                registry_entity("sensor.ap_clients", "unifi", "d1"),
                "living_room",
            ),
            (
                "unifiprotect device",
                registry_device("living_room"),
                registry_entity("camera.living_room", "unifiprotect", "d1"),
                "living_room",
            ),
            (
                "backup",
                None,
                registry_entity("sensor.backup_state", "backup"),
                "living_room",
            ),
            (
                "sun",
                None,
                registry_entity("sensor.sun_next_dawn", "sun"),
                "living_room",
            ),
            ("hassio", None, registry_entity("update.core", "hassio"), "living_room"),
        ]
        for label, device, entity, area_id in cases:
            with self.subTest(label):
                self.assertFalse(in_scope(device, entity, area_id))

    def test_in_scope_includes(self):
        cases = [
            (
                "device with area",
                registry_device("living_room"),
                registry_entity("light.a", "hue", "d1"),
                "living_room",
            ),
            (
                "own entity with area",
                None,
                registry_entity("input_number.living_room_x", "input_number"),
                "living_room",
            ),
        ]
        for label, device, entity, area_id in cases:
            with self.subTest(label):
                self.assertTrue(in_scope(device, entity, area_id))


if __name__ == "__main__":
    unittest.main()
