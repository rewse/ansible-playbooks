"""Tests for the Home Assistant naming migration tool."""

import pathlib
import sys
import tempfile
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

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


if __name__ == "__main__":
    unittest.main()
