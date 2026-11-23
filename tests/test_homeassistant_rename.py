"""Tests for the Home Assistant naming migration tool."""

import pathlib
import re
import sys
import tempfile
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.homeassistant_rename.mapping import Row
from tools.homeassistant_rename.mapping import YamlSources
from tools.homeassistant_rename.mapping import build_rows
from tools.homeassistant_rename.mapping import load_yaml_sources
from tools.homeassistant_rename.mapping import read_csv
from tools.homeassistant_rename.mapping import write_csv
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


def fake_slugify(names: list[str]) -> dict[str, str]:
    """Approximates Home Assistant's slugify for the names in these tests."""
    return {
        name: re.sub(r"[^a-z0-9]+", "_", name.replace("’", "").lower()).strip("_")
        for name in names
    }


def area(area_id: str, name: str) -> dict:
    return {"area_id": area_id, "name": name}


def device(device_id: str, area_id: str | None, name: str, domain: str = "hue") -> dict:
    return {
        "area_id": area_id,
        "id": device_id,
        "identifiers": [[domain, device_id]],
        "name": name,
        "name_by_user": None,
        "parent_device_id": None,
    }


def entity(
    entity_id: str,
    device_id: str | None = None,
    *,
    area_id: str | None = None,
    name: str | None = None,
    original_name: str | None = None,
    platform: str = "hue",
    unique_id: str = "u",
) -> dict:
    return {
        "area_id": area_id,
        "device_id": device_id,
        "entity_id": entity_id,
        "name": name,
        "original_name": original_name,
        "platform": platform,
        "unique_id": unique_id,
    }


NO_YAML = YamlSources(key_ids=set(), unique_ids=set())


def mapping_snapshot(devices: list[dict], entities: list[dict]) -> Snapshot:
    return Snapshot(
        areas=[
            area("balcony", "Balcony"),
            area("dads_room", "Dad’s Room"),
            area("living_room", "Living Room"),
        ],
        devices=devices,
        entities=entities,
        states={},
    )


def rows_by_key(rows: list[Row]) -> dict[str, Row]:
    return {row.key: row for row in rows}


class MappingTest(unittest.TestCase):
    def test_device_entity_id_follows_area_device_entity(self):
        calls = []

        def slugify(names: list[str]) -> dict[str, str]:
            calls.append(names)
            return fake_slugify(names)

        snapshot = mapping_snapshot(
            [device("d1", "living_room", "Living Room Thermometer")],
            [
                entity(
                    "sensor.living_room_temperature",
                    "d1",
                    original_name="Temperature",
                )
            ],
        )
        rows = rows_by_key(build_rows(snapshot, NO_YAML, slugify))
        self.assertEqual(rows["d1"].new_name, "Thermometer")
        self.assertEqual(rows["d1"].status, "auto")
        entity_row = rows["sensor.living_room_temperature"]
        self.assertEqual(
            entity_row.new_id, "sensor.living_room_thermometer_temperature"
        )
        self.assertEqual(entity_row.room, "living_room")
        self.assertEqual(entity_row.status, "auto")
        self.assertEqual(len(calls), 1)

    def test_main_entity_uses_device_name_only(self):
        snapshot = mapping_snapshot(
            [device("d1", "living_room", "Living Room Humidifier Plug", "tplink")],
            [
                entity(
                    "switch.humidifier_plug",
                    "d1",
                    name="",
                    original_name="Switch",
                    platform="tplink",
                )
            ],
        )
        rows = rows_by_key(build_rows(snapshot, NO_YAML, fake_slugify))
        self.assertEqual(
            rows["switch.humidifier_plug"].new_id, "switch.living_room_humidifier_plug"
        )

    def test_area_rows_use_ascii_apostrophe(self):
        snapshot = mapping_snapshot(
            [device("d1", "dads_room", "Dad’s Room AC", "tuya")],
            [entity("climate.dads_room_ac", "d1", original_name=None, platform="tuya")],
        )
        rows = rows_by_key(build_rows(snapshot, NO_YAML, fake_slugify))
        self.assertEqual(rows["dads_room"].new_name, "Dad's Room")
        self.assertEqual(rows["dads_room"].status, "auto")
        self.assertEqual(rows["d1"].new_name, "AC")
        self.assertTrue(
            rows["climate.dads_room_ac"].new_id.startswith("climate.dad_s_room_")
        )

    def test_thermometer_pairs_get_primary_and_secondary(self):
        snapshot = mapping_snapshot(
            [
                device("d1", "dads_room", "Dad’s Room Thermometer", "zha"),
                device("d2", "dads_room", "Dad’s Room SwitchBot Meter", "switchbot"),
                device("b1", "balcony", "Balcony SwitchBot Outdoor Meter", "switchbot"),
                device("b2", "balcony", "Balcony SwitchBot Meter", "switchbot"),
                device("l1", "living_room", "Living Room SwitchBot Meter", "switchbot"),
            ],
            [],
        )
        rows = rows_by_key(build_rows(snapshot, NO_YAML, fake_slugify))
        self.assertEqual(rows["d1"].new_name, "Thermometer Primary")
        self.assertEqual(rows["d2"].new_name, "Thermometer Secondary")
        self.assertEqual(rows["b1"].new_name, "Thermometer Primary")
        self.assertEqual(rows["b2"].new_name, "Thermometer Secondary")
        self.assertEqual(rows["l1"].new_name, "Thermometer")

    def test_yaml_key_helpers_are_marked(self):
        entity_id = "input_number.living_room_temp_target"
        snapshot = mapping_snapshot(
            [],
            [
                entity(
                    entity_id,
                    original_name="Living Room Temp Target",
                    platform="input_number",
                    unique_id="living_room_temp_target",
                )
            ],
        )
        yaml_sources = YamlSources(key_ids={entity_id}, unique_ids=set())
        row = rows_by_key(build_rows(snapshot, yaml_sources, fake_slugify))[entity_id]
        self.assertEqual(row.source, "yaml_key")
        self.assertEqual(row.new_id, "input_number.living_room_temperature_target")
        self.assertEqual(row.new_name, "Temperature Target")
        self.assertEqual(row.room, "living_room")
        self.assertEqual(row.status, "auto")

    def test_yaml_unique_id_entities_keep_unique_id(self):
        entity_id = "binary_sensor.dads_room_humidity_high"
        snapshot = mapping_snapshot(
            [],
            [
                entity(
                    entity_id,
                    original_name="Dad’s Room Humidity High",
                    platform="template",
                    unique_id=entity_id,
                )
            ],
        )
        yaml_sources = YamlSources(key_ids=set(), unique_ids={entity_id})
        row = rows_by_key(build_rows(snapshot, yaml_sources, fake_slugify))[entity_id]
        self.assertEqual(row.source, "yaml_unique_id")
        self.assertEqual(row.new_id, "binary_sensor.dad_s_room_humidity_high")
        self.assertEqual(row.room, "dads_room")

    def test_study_prefix_needs_review(self):
        entity_id = "input_boolean.study_light_auto"
        snapshot = mapping_snapshot(
            [],
            [
                entity(
                    entity_id,
                    original_name="Study Light Auto",
                    platform="input_boolean",
                )
            ],
        )
        row = rows_by_key(build_rows(snapshot, NO_YAML, fake_slugify))[entity_id]
        self.assertEqual(row.new_id, "input_boolean.living_room_light_auto")
        self.assertEqual(row.status, "review")
        self.assertIn("study_", row.note)

    def test_unknown_area_of_own_entity_needs_review(self):
        cases = [
            ("input_boolean.garage_light_auto", "garage"),
            ("input_boolean.moms_room_light_auto", None),
        ]
        for entity_id, area_id in cases:
            with self.subTest(entity_id):
                snapshot = mapping_snapshot(
                    [],
                    [
                        entity(
                            entity_id,
                            area_id=area_id,
                            original_name="Light Auto",
                            platform="input_boolean",
                        )
                    ],
                )
                row = rows_by_key(build_rows(snapshot, NO_YAML, fake_slugify))[
                    entity_id
                ]
                self.assertEqual(row.status, "review")
                self.assertIn("unknown area", row.note)
                self.assertEqual(row.new_id, entity_id)

    def test_unknown_area_of_device_entity_needs_review(self):
        snapshot = mapping_snapshot(
            [device("d1", "garage", "Garage Light")],
            [entity("light.garage_light", "d1")],
        )
        row = rows_by_key(build_rows(snapshot, NO_YAML, fake_slugify))[
            "light.garage_light"
        ]
        self.assertEqual(row.status, "review")
        self.assertIn("unknown area garage", row.note)
        self.assertEqual(row.new_id, "light.garage_light")

    def test_product_names_need_review(self):
        cases = [
            ("Aventage", True),
            ("Floor Heater North", False),
            ("Roomba Combo", True),
            ("SwitchBot Hub 2", True),
            ("Thermometer", False),
            ("eufy-ent", True),
            ("regza", True),
            ("switchbothub", True),
        ]
        for name, flagged in cases:
            with self.subTest(name):
                snapshot = mapping_snapshot(
                    [device("d1", "living_room", f"Living Room {name}")], []
                )
                row = rows_by_key(build_rows(snapshot, NO_YAML, fake_slugify))["d1"]
                if flagged:
                    self.assertEqual(row.status, "review")
                    self.assertIn("product name", row.note)
                else:
                    self.assertNotIn("product name", row.note)
                    self.assertEqual(row.status, "auto")

    def test_thermometer_pair_names_are_not_product_names(self):
        snapshot = mapping_snapshot(
            [
                device("b1", "balcony", "Balcony SwitchBot Outdoor Meter", "switchbot"),
                device("b2", "balcony", "Balcony SwitchBot Meter", "switchbot"),
            ],
            [],
        )
        rows = rows_by_key(build_rows(snapshot, NO_YAML, fake_slugify))
        for key in ("b1", "b2"):
            with self.subTest(key):
                self.assertEqual(rows[key].status, "auto")
                self.assertEqual(rows[key].note, "")

    def test_duplicate_targets_are_flagged(self):
        snapshot = mapping_snapshot(
            [
                device("d1", "living_room", "Living Room Light", "hue"),
                device("d2", "living_room", "Light", "hue"),
            ],
            [
                entity("light.living_room_light", "d1"),
                entity("light.light", "d2"),
            ],
        )
        rows = rows_by_key(build_rows(snapshot, NO_YAML, fake_slugify))
        for key in ("light.living_room_light", "light.light"):
            with self.subTest(key):
                self.assertEqual(rows[key].status, "review")
                self.assertIn("conflict", rows[key].note)

    def test_unchanged_rows_are_skipped(self):
        snapshot = mapping_snapshot(
            [device("d1", "living_room", "Thermometer")],
            [
                entity(
                    "sensor.living_room_thermometer_temperature",
                    "d1",
                    original_name="Temperature",
                )
            ],
        )
        rows = rows_by_key(build_rows(snapshot, NO_YAML, fake_slugify))
        self.assertEqual(rows["living_room"].status, "skip")
        self.assertEqual(rows["d1"].status, "skip")
        self.assertEqual(
            rows["sensor.living_room_thermometer_temperature"].status, "skip"
        )

    def test_out_of_scope_rows_are_skipped_without_room(self):
        snapshot = mapping_snapshot(
            [device("d1", None, "Hallway Bulb")],
            [
                entity("light.hallway_bulb", "d1"),
                entity("person.tats", platform="person"),
            ],
        )
        rows = rows_by_key(build_rows(snapshot, NO_YAML, fake_slugify))
        for key in ("d1", "light.hallway_bulb", "person.tats"):
            with self.subTest(key):
                self.assertEqual(rows[key].status, "skip")
                self.assertEqual(rows[key].room, "")

    def test_csv_round_trip(self):
        snapshot = mapping_snapshot(
            [device("d1", "dads_room", "Dad’s Room Thermometer", "zha")],
            [entity("sensor.dads_room_temperature", "d1", original_name="Temperature")],
        )
        rows = build_rows(snapshot, NO_YAML, fake_slugify)
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "mapping.csv"
            write_csv(rows, path)
            self.assertEqual(read_csv(path), rows)
            header = path.read_text(encoding="utf-8").splitlines()[0]
            self.assertEqual(
                header,
                "room,kind,source,integration,key,old_name,new_name,old_id,new_id,status,note",
            )

    def test_csv_rejects_unknown_status(self):
        row = Row(
            room="living_room",
            kind="area",
            source="registry",
            integration="",
            key="living_room",
            old_name="Living Room",
            new_name="Living Room",
            old_id="",
            new_id="",
            status="skip",
            note="",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "mapping.csv"
            write_csv([row], path)
            path.write_text(
                path.read_text(encoding="utf-8").replace(",skip,", ",done,"),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                read_csv(path)

    def test_load_yaml_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            files_dir = pathlib.Path(tmp)
            for name in (
                "input_booleans.yaml",
                "input_datetimes.yaml",
                "input_selects.yaml",
            ):
                (files_dir / name).write_text("", encoding="utf-8")
            (files_dir / "input_numbers.yaml").write_text(
                '# Living Room\n\nliving_room_temp_target:\n  name: "x"\n  min: 0\n',
                encoding="utf-8",
            )
            (files_dir / "scripts.yaml").write_text(
                'darken_living_room:\n  alias: "Darken"\n', encoding="utf-8"
            )
            (files_dir / "templates.yaml").write_text(
                "- binary_sensor:\n  - unique_id: binary_sensor.dads_room_x\n",
                encoding="utf-8",
            )
            (files_dir / "automations-x.yaml").write_text(
                "- id: automation.x\n  triggers:\n    - trigger: state\n      id: t\n",
                encoding="utf-8",
            )
            sources = load_yaml_sources(files_dir)
        self.assertEqual(
            sources.key_ids,
            {"input_number.living_room_temp_target", "script.darken_living_room"},
        )
        self.assertEqual(
            sources.unique_ids, {"automation.x", "binary_sensor.dads_room_x"}
        )


if __name__ == "__main__":
    unittest.main()
