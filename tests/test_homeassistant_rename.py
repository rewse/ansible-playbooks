"""Tests for the Home Assistant naming migration tool."""

import asyncio
import contextlib
import io
import json
import pathlib
import re
import sys
import tempfile
import unittest
from typing import Any
from unittest import mock

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import tools.homeassistant_rename.__main__ as cli_module
from tools.homeassistant_rename.__main__ import main as cli_main
from tools.homeassistant_rename.hass import HassError
from tools.homeassistant_rename.mapping import KEY_ID_FILES
from tools.homeassistant_rename.mapping import Override
from tools.homeassistant_rename.mapping import Row
from tools.homeassistant_rename.mapping import Source
from tools.homeassistant_rename.mapping import Status
from tools.homeassistant_rename.mapping import YamlSources
from tools.homeassistant_rename.mapping import build_rows
from tools.homeassistant_rename.mapping import load_yaml_sources
from tools.homeassistant_rename.mapping import read_csv
from tools.homeassistant_rename.mapping import read_overrides
from tools.homeassistant_rename.mapping import validate
from tools.homeassistant_rename.mapping import write_csv
from tools.homeassistant_rename.registry import Op
from tools.homeassistant_rename.registry import apply_ops
from tools.homeassistant_rename.registry import assign_areas
from tools.homeassistant_rename.registry import plan_ops
from tools.homeassistant_rename.registry import remove_orphans
from tools.homeassistant_rename.registry import revert
from tools.homeassistant_rename.rewrite import check
from tools.homeassistant_rename.rewrite import rewrite_repo
from tools.homeassistant_rename.rewrite import rewrite_storage
from tools.homeassistant_rename.rewrite import rewrite_text
from tools.homeassistant_rename.rewrite import rewrite_yaml_keys
from tools.homeassistant_rename.rewrite import rewrite_yaml_names
from tools.homeassistant_rename.rules import expand_abbreviations
from tools.homeassistant_rename.rules import in_scope
from tools.homeassistant_rename.rules import normalize_apostrophe
from tools.homeassistant_rename.rules import normalize_modifiers
from tools.homeassistant_rename.rules import strip_area
from tools.homeassistant_rename.snapshot import Snapshot
from tools.homeassistant_rename.values import capture
from tools.homeassistant_rename.values import restore
from tools.homeassistant_rename.values import restore_calls


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

    def test_names_with_rule_gaps_need_review(self):
        cases = [
            ("Living Room Study Window Sensor N", "direction abbreviation N"),
            ("Living Room Window Sensor NE Left", "direction abbreviation NE"),
            ("Dad’s Room Camera (Dad's Room Camera)", "area name Dad's Room"),
            ("Living Room Lamp (living room)", "area name Living Room"),
        ]
        for name, reason in cases:
            with self.subTest(name):
                snapshot = mapping_snapshot([device("d1", "dads_room", name)], [])
                row = rows_by_key(build_rows(snapshot, NO_YAML, fake_slugify))["d1"]
                self.assertEqual(row.status, "review")
                self.assertIn(reason, row.note)

    def test_words_that_contain_a_direction_or_area_are_not_flagged(self):
        snapshot = mapping_snapshot(
            [device("d1", "living_room", "Living Room Nest Balconyx Window Sensor")],
            [],
        )
        row = rows_by_key(build_rows(snapshot, NO_YAML, fake_slugify))["d1"]
        self.assertEqual(row.status, "auto", row.note)

    def test_repeated_tokens_in_new_ids_need_review(self):
        cases = [
            (
                "switch.living_room_motion_sensor_motion",
                entity(
                    "switch.living_room_motion_sensor_motion",
                    "d1",
                    original_name="Motion Sensor Enabled",
                ),
                "switch.living_room_motion_sensor_motion_sensor_enabled",
            ),
            (
                "sensor.living_room_camera_fps",
                entity(
                    "sensor.living_room_camera_fps", "d2", original_name="Camera FPS"
                ),
                "sensor.living_room_camera_camera_fps",
            ),
            (
                "sensor.dads_room_room_wbgt",
                entity("sensor.dads_room_room_wbgt", platform="template"),
                "sensor.dad_s_room_room_wbgt",
            ),
        ]
        snapshot = mapping_snapshot(
            [
                device("d1", "living_room", "Living Room Motion Sensor"),
                device("d2", "living_room", "Living Room Camera"),
            ],
            [case[1] for case in cases],
        )
        rows = rows_by_key(build_rows(snapshot, NO_YAML, fake_slugify))
        for key, _, new_id in cases:
            with self.subTest(key):
                self.assertEqual(rows[key].new_id, new_id)
                self.assertEqual(rows[key].status, "review")
                self.assertIn("repeated", rows[key].note)

    def test_unchanged_rows_are_not_flagged(self):
        snapshot = mapping_snapshot(
            [], [entity("sensor.dad_s_room_room_wbgt", platform="template")]
        )
        row = rows_by_key(build_rows(snapshot, NO_YAML, fake_slugify))[
            "sensor.dad_s_room_room_wbgt"
        ]
        self.assertEqual(row.status, "skip")

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


def entity_row(
    old_id: str,
    new_id: str,
    *,
    source: Source = "registry",
    status: Status = "auto",
    old_name: str = "",
    new_name: str = "",
    room: str = "dads_room",
) -> Row:
    return Row(
        room=room,
        kind="entity",
        source=source,
        integration="",
        key=old_id,
        old_name=old_name,
        new_name=new_name,
        old_id=old_id,
        new_id=new_id,
        status=status,
        note="",
    )


def overrides_from(text: str) -> list[Override]:
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "overrides.csv"
        path.write_text(text, encoding="utf-8")
        return read_overrides(path)


def hue_room_snapshot() -> Snapshot:
    """A Hue room group named after its area, with a light and a scene."""
    return mapping_snapshot(
        [
            device("d1", "dads_room", "Dad’s Room"),
            device("d2", "dads_room", "Dad’s Room SwitchBot Meter", "switchbot"),
        ],
        [
            entity("light.dads_room", "d1"),
            entity("scene.dads_room_arise", "d1", original_name="Arise"),
            entity(
                "sensor.dads_room_switchbot_meter_temperature",
                "d2",
                original_name="Temeperature",
                platform="switchbot",
            ),
        ],
    )


class OverrideTest(unittest.TestCase):
    def test_entities_of_a_device_under_review_need_review(self):
        rows = rows_by_key(build_rows(hue_room_snapshot(), NO_YAML, fake_slugify))
        self.assertEqual(rows["d1"].status, "review")
        for key in ("light.dads_room", "scene.dads_room_arise"):
            with self.subTest(key):
                self.assertEqual(rows[key].status, "review")
                self.assertIn("device under review", rows[key].note)

    def test_device_override_renames_its_entities(self):
        overrides = overrides_from("kind,key,new_name\ndevice,d1,Ceiling Light\n")
        rows = rows_by_key(
            build_rows(hue_room_snapshot(), NO_YAML, fake_slugify, overrides)
        )
        self.assertEqual(rows["d1"].new_name, "Ceiling Light")
        self.assertEqual(rows["d1"].status, "auto")
        self.assertEqual(rows["d1"].note, "")
        self.assertEqual(
            rows["light.dads_room"].new_id, "light.dad_s_room_ceiling_light"
        )
        self.assertEqual(rows["light.dads_room"].status, "auto")
        self.assertEqual(
            rows["scene.dads_room_arise"].new_id,
            "scene.dad_s_room_ceiling_light_arise",
        )

    def test_device_override_is_checked_like_a_generated_name(self):
        overrides = overrides_from("kind,key,new_name\ndevice,d1,Light 2\n")
        rows = rows_by_key(
            build_rows(hue_room_snapshot(), NO_YAML, fake_slugify, overrides)
        )
        self.assertEqual(rows["d1"].status, "review")
        self.assertIn("numbered", rows["d1"].note)
        self.assertEqual(rows["light.dads_room"].status, "review")

    def test_entity_override_sets_entity_name(self):
        overrides = overrides_from(
            "kind,key,new_name,new_id,status\n"
            "entity,sensor.dads_room_switchbot_meter_temperature,Temperature,,\n"
        )
        rows = rows_by_key(
            build_rows(hue_room_snapshot(), NO_YAML, fake_slugify, overrides)
        )
        row = rows["sensor.dads_room_switchbot_meter_temperature"]
        self.assertEqual(row.new_name, "Temperature")
        self.assertEqual(row.new_id, "sensor.dad_s_room_thermometer_temperature")
        self.assertEqual(row.status, "auto")

    def test_entity_override_pins_id_and_status(self):
        overrides = overrides_from(
            "kind,key,new_name,new_id,status\n"
            "entity,light.dads_room,,light.dad_s_room_light_light,auto\n"
            "entity,scene.dads_room_arise,Arise,scene.dad_s_room_arise,\n"
        )
        rows = rows_by_key(
            build_rows(hue_room_snapshot(), NO_YAML, fake_slugify, overrides)
        )
        light = rows["light.dads_room"]
        self.assertEqual(light.new_id, "light.dad_s_room_light_light")
        self.assertEqual(light.status, "auto")
        scene = rows["scene.dads_room_arise"]
        self.assertEqual(scene.new_id, "scene.dad_s_room_arise")
        self.assertEqual(scene.status, "auto", scene.note)

    def test_own_entity_override_pins_id(self):
        entity_id = "input_boolean.study_light_auto"
        snapshot = mapping_snapshot(
            [],
            [entity(entity_id, original_name="Study Light Auto", platform="x")],
        )
        overrides = overrides_from(
            "kind,key,new_name,new_id\n"
            f"entity,{entity_id},Light Auto North,"
            "input_boolean.living_room_light_auto_north\n"
        )
        row = rows_by_key(build_rows(snapshot, NO_YAML, fake_slugify, overrides))[
            entity_id
        ]
        self.assertEqual(row.new_id, "input_boolean.living_room_light_auto_north")
        self.assertEqual(row.new_name, "Light Auto North")
        self.assertEqual(row.status, "auto", row.note)

    def test_conflicts_are_recomputed_after_overrides(self):
        overrides = overrides_from(
            "kind,key,new_name,new_id,status\ndevice,d1,Thermometer,,auto\n"
        )
        rows = rows_by_key(
            build_rows(hue_room_snapshot(), NO_YAML, fake_slugify, overrides)
        )
        for key in ("d1", "d2"):
            with self.subTest(key):
                self.assertEqual(rows[key].status, "review")
                self.assertIn("conflict", rows[key].note)

    def test_invalid_overrides_are_rejected(self):
        cases = [
            "kind,key,new_name\ndevice,missing,X\n",
            "kind,key,new_name\nentity,light.missing,X\n",
            "kind,key,new_name,new_id\nentity,light.dads_room,,switch.x\n",
        ]
        for text in cases:
            with self.subTest(text), self.assertRaises(ValueError):
                build_rows(
                    hue_room_snapshot(),
                    NO_YAML,
                    fake_slugify,
                    overrides_from(text),
                )
        for text in (
            "kind,key\ndevice,d1\n",
            "kind,key,new_name,status\ndevice,d1,X,done\n",
            "kind,key,new_name\ndevice,d1,X\ndevice,d1,Y\n",
        ):
            with self.subTest(text), self.assertRaises(ValueError):
                overrides_from(text)

    def test_override_of_a_row_out_of_scope_is_rejected(self):
        snapshot = mapping_snapshot(
            [device("d1", None, "Hallway Bulb")], [entity("light.hallway_bulb", "d1")]
        )
        for text in (
            "kind,key,new_name\ndevice,d1,Bulb\n",
            "kind,key,new_name\nentity,light.hallway_bulb,Bulb\n",
        ):
            with self.subTest(text), self.assertRaises(ValueError):
                build_rows(snapshot, NO_YAML, fake_slugify, overrides_from(text))

    def test_map_cli_applies_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            hue_room_snapshot().save(root / "snapshot.json")
            files = root / "files"
            files.mkdir()
            for name in KEY_ID_FILES.values():
                (files / name).write_text("", encoding="utf-8")
            (root / "overrides.csv").write_text(
                "kind,key,new_name\ndevice,d1,Ceiling Light\n", encoding="utf-8"
            )
            with (
                mock.patch.object(cli_module, "hass_slugify", fake_slugify),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                status = cli_main(
                    [
                        "map",
                        "--files",
                        str(files),
                        "--out",
                        str(root / "mapping.csv"),
                        "--overrides",
                        str(root / "overrides.csv"),
                        "--snapshot",
                        str(root / "snapshot.json"),
                    ]
                )
            rows = rows_by_key(read_csv(root / "mapping.csv"))
        self.assertEqual(status, 0)
        self.assertEqual(
            rows["light.dads_room"].new_id, "light.dad_s_room_ceiling_light"
        )


class ValidateTest(unittest.TestCase):
    def test_lists_review_duplicate_and_held_ids(self):
        snapshot = Snapshot(
            areas=[],
            devices=[],
            entities=[
                {"entity_id": "light.a"},
                {"entity_id": "light.b"},
                {"entity_id": "light.c"},
                {"entity_id": "light.d"},
                {"entity_id": "light.e"},
            ],
            states={"light.state_only": {}},
        )
        rows = [
            entity_row("light.a", "light.x"),
            entity_row("light.b", "light.x"),
            entity_row("light.c", "light.d"),
            entity_row("light.d", "light.y", status="review"),
            entity_row("light.e", "light.state_only"),
        ]
        problems = validate(rows, snapshot)
        self.assertEqual(
            problems,
            [
                "light.d: still review",
                "light.x: new ID of light.a, light.b",
                "light.c: new ID light.d is held by an entity that is not renamed",
                (
                    "light.e: new ID light.state_only is held by an entity that is "
                    "not renamed"
                ),
            ],
        )

    def test_chains_and_swaps_pass(self):
        snapshot = Snapshot(
            areas=[],
            devices=[],
            entities=[{"entity_id": "light.a"}, {"entity_id": "light.b"}],
            states={},
        )
        rows = [entity_row("light.a", "light.b"), entity_row("light.b", "light.a")]
        self.assertEqual(validate(rows, snapshot), [])

    def test_validate_cli_exit_code(self):
        snapshot = Snapshot(
            areas=[], devices=[], entities=[{"entity_id": "light.a"}], states={}
        )
        for rows, expected in (
            ([entity_row("light.a", "light.b")], 0),
            ([entity_row("light.a", "light.b", status="review")], 1),
        ):
            with self.subTest(expected), tempfile.TemporaryDirectory() as tmp:
                root = pathlib.Path(tmp)
                snapshot.save(root / "snapshot.json")
                write_csv(rows, root / "mapping.csv")
                with contextlib.redirect_stdout(io.StringIO()) as stdout:
                    status = cli_main(
                        [
                            "validate",
                            "--mapping",
                            str(root / "mapping.csv"),
                            "--snapshot",
                            str(root / "snapshot.json"),
                        ]
                    )
                self.assertEqual(status, expected, stdout.getvalue())


class RewriteTest(unittest.TestCase):
    def test_rewrites_states_attribute_access(self):
        self.assertEqual(
            rewrite_text(
                "states.sensor.living_room_temperature.last_changed",
                {
                    "sensor.living_room_temperature": (
                        "sensor.living_room_thermometer_temperature"
                    )
                },
            ),
            "states.sensor.living_room_thermometer_temperature.last_changed",
        )

    def test_does_not_touch_longer_ids(self):
        text = (
            "switch.living_room_humidifier switch.living_room_humidifier_plug "
            "switch.living_room_humidifier_switch"
        )
        out = rewrite_text(text, {"switch.living_room_humidifier": "switch.x"})
        self.assertEqual(
            out,
            "switch.x switch.living_room_humidifier_plug "
            "switch.living_room_humidifier_switch",
        )

    def test_does_not_chain_replacements(self):
        out = rewrite_text(
            "sensor.a sensor.b", {"sensor.a": "sensor.b", "sensor.b": "sensor.c"}
        )
        self.assertEqual(out, "sensor.b sensor.c")

    def test_unique_id_and_id_values_are_kept(self):
        text = (
            "- id: automation.alarm_dads_room_co2\n"
            '  alias: "ALARM: CO2"\n'
            "  triggers:\n"
            "    - trigger: numeric_state\n"
            "      entity_id: sensor.dads_room_co2\n"
            "sensor:\n"
            "  - unique_id: sensor.dads_room_co2\n"
            "    state: \"{{ states('sensor.dads_room_co2') }}\"\n"
        )
        id_map = {
            "automation.alarm_dads_room_co2": "automation.alarm_dad_s_room_co2",
            "sensor.dads_room_co2": "sensor.dad_s_room_co2",
        }
        out = rewrite_text(text, id_map).splitlines()
        self.assertEqual(out[0], "- id: automation.alarm_dads_room_co2")
        self.assertEqual(out[4], "      entity_id: sensor.dad_s_room_co2")
        self.assertEqual(out[6], "  - unique_id: sensor.dads_room_co2")
        self.assertEqual(out[7], "    state: \"{{ states('sensor.dad_s_room_co2') }}\"")

    def test_yaml_keys_are_renamed(self):
        text = (
            "# Living Room\n"
            "\n"
            "living_room_temp_target:\n"
            '  name: "Living Room Temp Target"\n'
            "  min: 0\n"
            "living_room_temp_target_away:\n"
            '  name: "Living Room Temp Target Away"\n'
            "  min: 0\n"
        )
        out = rewrite_yaml_keys(
            text,
            {
                "living_room_temp_target": (
                    "living_room_temperature_target",
                    "Temperature Target",
                )
            },
        )
        self.assertEqual(
            out,
            "# Living Room\n"
            "\n"
            "living_room_temperature_target:\n"
            '  name: "Temperature Target"\n'
            "  min: 0\n"
            "living_room_temp_target_away:\n"
            '  name: "Living Room Temp Target Away"\n'
            "  min: 0\n",
        )

    def test_script_alias_follows_key(self):
        text = 'darken_living_room:\n  alias: "Darken Living Room"\n  sequence: []\n'
        out = rewrite_yaml_keys(
            text, {"darken_living_room": ("living_room_darken", "Darken")}
        )
        self.assertEqual(
            out, 'living_room_darken:\n  alias: "Darken"\n  sequence: []\n'
        )

    def test_yaml_names_follow_unique_id(self):
        text = (
            "- binary_sensor:\n"
            "  # Dad’s Room\n"
            "  - unique_id: binary_sensor.dads_room_ac_cooldry\n"
            '    name: "Dad’s Room AC CoolDry"\n'
            "  - unique_id: binary_sensor.dads_room_humidity_disagreement\n"
            '    name: "Dad’s Room Humidity Disagreement"\n'
            "    delay_on:\n"
            "      hours: 1\n"
            "- platform: statistics\n"
            '  name: "Dad’s Room Humidity Smoothed"\n'
            "  unique_id: sensor.dads_room_humidity_smoothed\n"
            "- id: automation.alarm_dads_room_co2\n"
            '  alias: "ALARM: Dad’s Room CO2"\n'
            "  triggers:\n"
            "    - trigger: state\n"
            "      id: t\n"
        )
        out = rewrite_yaml_names(
            text,
            {
                "automation.alarm_dads_room_co2": "ALARM: CO2",
                "binary_sensor.dads_room_humidity_disagreement": "Humidity Disagreement",
                "sensor.dads_room_humidity_smoothed": 'Humidity "Smoothed"',
            },
        ).splitlines()
        self.assertEqual(out[3], '    name: "Dad’s Room AC CoolDry"')
        self.assertEqual(
            out[4], "  - unique_id: binary_sensor.dads_room_humidity_disagreement"
        )
        self.assertEqual(out[5], '    name: "Humidity Disagreement"')
        self.assertEqual(out[9], '  name: "Humidity \\"Smoothed\\""')
        self.assertEqual(out[11], "- id: automation.alarm_dads_room_co2")
        self.assertEqual(out[12], '  alias: "ALARM: CO2"')

    def test_rewrite_repo_keeps_unique_ids_in_tests(self):
        rows = [
            entity_row(
                "automation.alarm_dads_room_co2",
                "automation.alarm_dad_s_room_co2",
                source="yaml_unique_id",
                old_name="ALARM: Dad’s Room CO2",
                new_name="ALARM: CO2",
            ),
            entity_row(
                "sensor.dads_room_temperature",
                "sensor.dad_s_room_thermometer_temperature",
            ),
            entity_row("sensor.dads_room_humidity", "sensor.x", status="review"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            files = root / "roles" / "homeassistant" / "files"
            role_tests = root / "roles" / "homeassistant" / "tests"
            files.mkdir(parents=True)
            role_tests.mkdir()
            (root / "roles" / "homeassistant" / "templates").mkdir()
            (root / "tests").mkdir()
            for name in KEY_ID_FILES.values():
                (files / name).write_text("", encoding="utf-8")
            (files / "automations-alarm.yaml").write_text(
                "- id: automation.alarm_dads_room_co2\n"
                '  alias: "ALARM: Dad’s Room CO2"\n'
                "  triggers:\n"
                "    - entity_id: sensor.dads_room_temperature\n"
                "    - entity_id: sensor.dads_room_humidity\n"
                "    - entity_id: automation.alarm_dads_room_co2\n",
                encoding="utf-8",
            )
            test_text = (
                "alarm_id: automation.alarm_dads_room_co2\n"
                "primary_entity_id: sensor.dads_room_temperature\n"
            )
            (role_tests / "x.yml").write_text(test_text, encoding="utf-8")
            (root / "tests" / "test_homeassistant_x.py").write_text(
                test_text, encoding="utf-8"
            )
            (root / "tests" / "test_homeassistant_rename.py").write_text(
                test_text, encoding="utf-8"
            )
            changed = rewrite_repo(root, rows)
            self.assertEqual(
                sorted(path.relative_to(root).as_posix() for path in changed),
                [
                    "roles/homeassistant/files/automations-alarm.yaml",
                    "roles/homeassistant/tests/x.yml",
                    "tests/test_homeassistant_x.py",
                ],
            )
            self.assertEqual(
                (files / "automations-alarm.yaml").read_text(encoding="utf-8"),
                "- id: automation.alarm_dads_room_co2\n"
                '  alias: "ALARM: CO2"\n'
                "  triggers:\n"
                "    - entity_id: sensor.dad_s_room_thermometer_temperature\n"
                "    - entity_id: sensor.dads_room_humidity\n"
                "    - entity_id: automation.alarm_dad_s_room_co2\n",
            )
            expected_test_text = (
                "alarm_id: automation.alarm_dads_room_co2\n"
                "primary_entity_id: sensor.dad_s_room_thermometer_temperature\n"
            )
            self.assertEqual(
                (role_tests / "x.yml").read_text(encoding="utf-8"), expected_test_text
            )
            self.assertEqual(
                (root / "tests" / "test_homeassistant_rename.py").read_text(
                    encoding="utf-8"
                ),
                test_text,
            )

    def test_check_reports_unknown_and_area_literals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            files = root / "roles" / "homeassistant" / "files"
            files.mkdir(parents=True)
            (files / "templates.yaml").write_text(
                "- sensor:\n"
                "  - unique_id: sensor.dads_room_old\n"
                '    name: "Dad’s Room Temperature"\n'
                "    state: \"{{ states('sensor.dads_room_temperature') }}\"\n"
                "    availability: \"{{ states('sensor.' ~ room ~ '_x') }}\"\n"
                "    attributes:\n"
                "      known: \"{{ states('sensor.dad_s_room_temperature') }}\"\n"
                "      service: light.turn_on\n"
                "      notify: notify.tats_devices\n",
                encoding="utf-8",
            )
            problems = check(root, {"sensor.dad_s_room_temperature"}, {"Dad’s Room"})
        self.assertEqual(len(problems), 3, problems)
        self.assertTrue(
            any(
                "templates.yaml:3:" in problem and "Dad’s Room" in problem
                for problem in problems
            ),
            problems,
        )
        self.assertTrue(
            any(
                "templates.yaml:4:" in problem
                and "sensor.dads_room_temperature" in problem
                for problem in problems
            ),
            problems,
        )
        self.assertTrue(
            any("templates.yaml:5:" in problem for problem in problems), problems
        )


class FakeClient:
    """Records calls and answers list commands from canned results."""

    def __init__(self, results: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.results = results or {}

    async def call(self, type_: str, **payload):
        self.calls.append((type_, payload))
        return self.results.get(type_)


def area_row(area_id: str, old_name: str, new_name: str) -> Row:
    return Row(
        room=area_id,
        kind="area",
        source="registry",
        integration="",
        key=area_id,
        old_name=old_name,
        new_name=new_name,
        old_id="",
        new_id="",
        status="auto",
        note="",
    )


def device_row(device_id: str, old_name: str, new_name: str) -> Row:
    return Row(
        room="dads_room",
        kind="device",
        source="registry",
        integration="hue",
        key=device_id,
        old_name=old_name,
        new_name=new_name,
        old_id="",
        new_id="",
        status="auto",
        note="",
    )


def renamed_ids(ops: list[Op]) -> list[tuple[str, str]]:
    return [(op.payload["entity_id"], op.payload["new_entity_id"]) for op in ops]


class RegistryTest(unittest.IsolatedAsyncioTestCase):
    def test_order_is_area_device_entity(self):
        rows = [
            entity_row("light.a", "light.b"),
            device_row("d1", "Dad’s Room Lamp", "Lamp"),
            area_row("dads_room", "Dad’s Room", "Dad's Room"),
        ]
        ops = plan_ops(rows, {"light.a"})
        self.assertEqual([op.kind for op in ops], ["area", "device", "entity"])
        self.assertEqual(ops[0].payload, {"area_id": "dads_room", "name": "Dad's Room"})
        self.assertEqual(ops[1].payload, {"device_id": "d1", "name_by_user": "Lamp"})

    def test_swap_uses_temporary_ids(self):
        rows = [entity_row("light.a", "light.b"), entity_row("light.b", "light.a")]
        ops = plan_ops(rows, {"light.a", "light.b"})
        self.assertEqual(
            renamed_ids(ops),
            [
                ("light.a", "light.a_renaming"),
                ("light.b", "light.a"),
                ("light.a_renaming", "light.b"),
            ],
        )

    def test_occupied_temporary_id_gets_a_number(self):
        rows = [entity_row("light.a", "light.b"), entity_row("light.b", "light.a")]
        ops = plan_ops(rows, {"light.a", "light.b", "light.a_renaming"})
        self.assertEqual(ops[0].payload["new_entity_id"], "light.a_renaming_2")

    def test_three_cycle_is_broken(self):
        rows = [
            entity_row("light.a", "light.b"),
            entity_row("light.b", "light.c"),
            entity_row("light.c", "light.a"),
        ]
        ops = plan_ops(rows, {"light.a", "light.b", "light.c"})
        self.assertEqual(
            renamed_ids(ops),
            [
                ("light.a", "light.a_renaming"),
                ("light.c", "light.a"),
                ("light.b", "light.c"),
                ("light.a_renaming", "light.b"),
            ],
        )

    def test_chain_is_ordered(self):
        rows = [entity_row("light.a", "light.b"), entity_row("light.b", "light.c")]
        ops = plan_ops(rows, {"light.a", "light.b"})
        self.assertEqual(
            renamed_ids(ops), [("light.b", "light.c"), ("light.a", "light.b")]
        )

    def test_target_held_by_another_entity_is_rejected(self):
        rows = [entity_row("light.a", "light.b")]
        with self.assertRaises(ValueError):
            plan_ops(rows, {"light.a", "light.b"})

    def test_only_auto_rows_produce_ops(self):
        rows = [
            entity_row("light.a", "light.b", status="review"),
            entity_row("light.c", "light.d", status="skip"),
        ]
        self.assertEqual(plan_ops(rows, {"light.a", "light.c"}), [])

    def test_entity_without_device_gets_its_room(self):
        snapshot = Snapshot(
            areas=[],
            devices=[],
            entities=[
                {
                    "area_id": None,
                    "device_id": None,
                    "entity_id": "sensor.dad_temp",
                    "name": None,
                },
                {
                    "area_id": None,
                    "device_id": "d1",
                    "entity_id": "light.dad_lamp",
                    "name": None,
                },
            ],
            states={},
        )
        rows = [
            entity_row(
                "sensor.dad_temp",
                "sensor.dads_room_temperature",
                source="yaml_unique_id",
            ),
            entity_row("light.dad_lamp", "light.dads_room_lamp"),
        ]
        ops = plan_ops(rows, {"sensor.dad_temp", "light.dad_lamp"}, snapshot)
        by_key = {op.key: op for op in ops}
        self.assertEqual(by_key["sensor.dad_temp"].payload["area_id"], "dads_room")
        self.assertIsNone(by_key["sensor.dad_temp"].undo["area_id"])
        self.assertNotIn("area_id", by_key["light.dad_lamp"].payload)

    async def test_dry_run_sends_nothing(self):
        client = FakeClient()
        ops = plan_ops([entity_row("light.a", "light.b")], {"light.a"})
        with tempfile.TemporaryDirectory() as tmp:
            journal = pathlib.Path(tmp) / "journal.jsonl"
            with contextlib.redirect_stdout(io.StringIO()):
                await apply_ops(client, ops, journal, dry_run=True)
            self.assertFalse(journal.exists())
        self.assertEqual(client.calls, [])

    async def test_journal_allows_revert(self):
        rows = [
            area_row("dads_room", "Dad’s Room", "Dad's Room"),
            entity_row("light.a", "light.b"),
            entity_row("light.b", "light.a"),
        ]
        ops = plan_ops(rows, {"light.a", "light.b"})
        client = FakeClient()
        with tempfile.TemporaryDirectory() as tmp:
            journal = pathlib.Path(tmp) / "journal.jsonl"
            await apply_ops(client, ops, journal, dry_run=False)
            self.assertEqual(len(journal.read_text().splitlines()), len(ops))
            applied = list(client.calls)
            client.calls.clear()
            await revert(client, journal)
        self.assertEqual(
            client.calls,
            [
                (
                    "config/entity_registry/update",
                    {"entity_id": "light.b", "new_entity_id": "light.a_renaming"},
                ),
                (
                    "config/entity_registry/update",
                    {"entity_id": "light.a", "new_entity_id": "light.b"},
                ),
                (
                    "config/entity_registry/update",
                    {"entity_id": "light.a_renaming", "new_entity_id": "light.a"},
                ),
                (
                    "config/area_registry/update",
                    {"area_id": "dads_room", "name": "Dad’s Room"},
                ),
            ],
        )
        self.assertEqual(len(applied), 4)

    async def test_revert_resumes_after_a_failure(self):
        class FailingClient(FakeClient):
            async def call(self, type_: str, **payload):
                if payload.get("entity_id") == "light.a":
                    raise HassError("connection lost")
                return await super().call(type_, **payload)

        rows = [entity_row("light.a", "light.b"), entity_row("light.b", "light.a")]
        ops = plan_ops(rows, {"light.a", "light.b"})
        with tempfile.TemporaryDirectory() as tmp:
            journal = pathlib.Path(tmp) / "journal.jsonl"
            await apply_ops(FakeClient(), ops, journal, dry_run=False)
            with self.assertRaises(HassError):
                await revert(FailingClient(), journal)
            self.assertEqual(len(journal.read_text().splitlines()), 2)
            client = FakeClient()
            await revert(client, journal)
        self.assertEqual(
            client.calls,
            [
                (
                    "config/entity_registry/update",
                    {"entity_id": "light.a", "new_entity_id": "light.b"},
                ),
                (
                    "config/entity_registry/update",
                    {"entity_id": "light.a_renaming", "new_entity_id": "light.a"},
                ),
            ],
        )

    def test_apply_after_a_full_revert_is_not_refused(self):
        class ClosingClient(FakeClient):
            async def close(self) -> None:
                pass

        async def fake_connect():
            return ClosingClient(
                {
                    "config/area_registry/list": [],
                    "config/device_registry/list": [],
                    "config/entity_registry/list": [],
                    "get_states": [],
                }
            )

        ops = plan_ops([entity_row("light.a", "light.b")], {"light.a"})
        with tempfile.TemporaryDirectory() as tmp:
            journal = pathlib.Path(tmp) / "journal.jsonl"
            asyncio.run(apply_ops(FakeClient(), ops, journal, dry_run=False))
            asyncio.run(revert(FakeClient(), journal))
            self.assertFalse(journal.exists())
            self.assertTrue((pathlib.Path(tmp) / "journal.jsonl.reverted").exists())
            mapping = pathlib.Path(tmp) / "mapping.csv"
            write_csv([], mapping)
            with (
                mock.patch.object(cli_module, "DEFAULT_JOURNAL", journal),
                mock.patch.object(cli_module, "connect", fake_connect),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                status = cli_main(["apply", "--mapping", str(mapping)])
        self.assertEqual(status, 0)

    async def test_failed_call_keeps_earlier_entries(self):
        class FailingClient(FakeClient):
            async def call(self, type_: str, **payload):
                if payload.get("entity_id") == "light.c":
                    raise HassError("rejected")
                return await super().call(type_, **payload)

        rows = [entity_row("light.a", "light.b"), entity_row("light.c", "light.d")]
        ops = plan_ops(rows, {"light.a", "light.c"})
        with tempfile.TemporaryDirectory() as tmp:
            journal = pathlib.Path(tmp) / "journal.jsonl"
            with self.assertRaises(HassError):
                await apply_ops(FailingClient(), ops, journal, dry_run=False)
            self.assertEqual(len(journal.read_text().splitlines()), 1)

    def test_apply_refuses_a_journal_with_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = pathlib.Path(tmp) / "journal.jsonl"
            journal.write_text("{}\n")
            mapping = pathlib.Path(tmp) / "mapping.csv"
            write_csv([], mapping)
            with contextlib.redirect_stderr(io.StringIO()) as stderr:
                status = cli_main(
                    ["apply", "--mapping", str(mapping), "--journal", str(journal)]
                )
        self.assertEqual(status, 1)
        self.assertIn("already records changes", stderr.getvalue())

    def test_yaml_key_rows_are_not_sent_to_registry(self):
        rows = [
            entity_row(
                "input_boolean.dad_away",
                "input_boolean.dads_room_away",
                source="yaml_key",
            )
        ]
        self.assertEqual(plan_ops(rows, {"input_boolean.dad_away"}), [])

    async def test_remove_orphans_skips_ids_with_state(self):
        rows = [
            entity_row("input_boolean.a", "input_boolean.x", source="yaml_key"),
            entity_row("input_boolean.b", "input_boolean.y", source="yaml_key"),
            entity_row("light.c", "light.z"),
        ]
        client = FakeClient(
            {
                "config/entity_registry/list": [
                    {"entity_id": "input_boolean.a"},
                    {"entity_id": "input_boolean.b"},
                    {"entity_id": "light.c"},
                ],
                "get_states": [{"entity_id": "input_boolean.b"}],
            }
        )
        removed = await remove_orphans(client, rows)
        self.assertEqual(removed, ["input_boolean.a"])
        self.assertIn(
            ("config/entity_registry/remove", {"entity_id": "input_boolean.a"}),
            client.calls,
        )
        self.assertEqual(
            [call for call in client.calls if call[0].endswith("/remove")],
            [("config/entity_registry/remove", {"entity_id": "input_boolean.a"})],
        )

    async def test_assign_areas_sets_room_on_registered_new_ids(self):
        rows = [
            entity_row("input_boolean.a", "input_boolean.x", source="yaml_key"),
            entity_row("input_boolean.b", "input_boolean.y", source="yaml_key"),
        ]
        client = FakeClient(
            {
                "config/entity_registry/list": [
                    {"area_id": None, "entity_id": "input_boolean.x"},
                ]
            }
        )
        await assign_areas(client, rows)
        self.assertEqual(
            client.calls[1:],
            [
                (
                    "config/entity_registry/update",
                    {"entity_id": "input_boolean.x", "area_id": "dads_room"},
                )
            ],
        )


def helper_state(entity_id: str, state: str, **attributes) -> dict:
    return {"attributes": attributes, "entity_id": entity_id, "state": state}


class ValuesTest(unittest.IsolatedAsyncioTestCase):
    def test_capture_keys_yaml_key_states_by_new_id(self):
        snapshot = Snapshot(
            areas=[],
            devices=[],
            entities=[],
            states={
                "input_boolean.dad_away": helper_state("input_boolean.dad_away", "on"),
                "light.a": helper_state("light.a", "on"),
            },
        )
        rows = [
            entity_row(
                "input_boolean.dad_away",
                "input_boolean.dads_room_away",
                source="yaml_key",
            ),
            entity_row(
                "input_boolean.missing", "input_boolean.other", source="yaml_key"
            ),
            entity_row(
                "input_boolean.held",
                "input_boolean.held_new",
                source="yaml_key",
                status="review",
            ),
            entity_row("light.a", "light.b"),
        ]
        self.assertEqual(
            capture(snapshot, rows),
            {
                "input_boolean.dads_room_away": helper_state(
                    "input_boolean.dad_away", "on"
                )
            },
        )

    def test_restore_calls_per_domain(self):
        captured = {
            "input_boolean.a": helper_state("input_boolean.old_a", "on"),
            "input_boolean.b": helper_state("input_boolean.old_b", "off"),
            "input_datetime.both": helper_state(
                "input_datetime.old_both",
                "2026-11-23 07:30:00",
                has_date=True,
                has_time=True,
            ),
            "input_datetime.date": helper_state(
                "input_datetime.old_date", "2026-11-23", has_date=True, has_time=False
            ),
            "input_datetime.time": helper_state(
                "input_datetime.old_time", "07:30:00", has_date=False, has_time=True
            ),
            "input_number.n": helper_state("input_number.old_n", "21.5"),
            "input_select.s": helper_state("input_select.old_s", "Away"),
            "script.x": helper_state("script.old_x", "off"),
        }
        self.assertEqual(
            restore_calls(captured),
            [
                ("input_boolean", "turn_on", {"entity_id": "input_boolean.a"}),
                ("input_boolean", "turn_off", {"entity_id": "input_boolean.b"}),
                (
                    "input_datetime",
                    "set_datetime",
                    {
                        "datetime": "2026-11-23 07:30:00",
                        "entity_id": "input_datetime.both",
                    },
                ),
                (
                    "input_datetime",
                    "set_datetime",
                    {"date": "2026-11-23", "entity_id": "input_datetime.date"},
                ),
                (
                    "input_datetime",
                    "set_datetime",
                    {"entity_id": "input_datetime.time", "time": "07:30:00"},
                ),
                (
                    "input_number",
                    "set_value",
                    {"entity_id": "input_number.n", "value": 21.5},
                ),
                (
                    "input_select",
                    "select_option",
                    {"entity_id": "input_select.s", "option": "Away"},
                ),
            ],
        )

    def test_unavailable_values_are_not_restored(self):
        captured = {
            "input_boolean.a": helper_state("input_boolean.old_a", "unavailable"),
            "input_number.n": helper_state("input_number.old_n", "unknown"),
        }
        self.assertEqual(restore_calls(captured), [])

    def test_capture_cli_writes_json(self):
        snapshot = Snapshot(
            areas=[],
            devices=[],
            entities=[],
            states={"input_number.a": helper_state("input_number.a", "3.0")},
        )
        rows = [entity_row("input_number.a", "input_number.b", source="yaml_key")]
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            snapshot.save(root / "snapshot.json")
            write_csv(rows, root / "mapping.csv")
            with contextlib.redirect_stdout(io.StringIO()):
                status = cli_main(
                    [
                        "capture",
                        "--mapping",
                        str(root / "mapping.csv"),
                        "--out",
                        str(root / "captured.json"),
                        "--snapshot",
                        str(root / "snapshot.json"),
                    ]
                )
            self.assertEqual(status, 0)
            self.assertEqual(
                json.loads((root / "captured.json").read_text()),
                {"input_number.b": helper_state("input_number.a", "3.0")},
            )

    async def test_restore_sends_call_service(self):
        client = FakeClient()
        await restore(
            client, {"input_select.s": helper_state("input_select.old_s", "Away")}
        )
        self.assertEqual(
            client.calls,
            [
                (
                    "call_service",
                    {
                        "domain": "input_select",
                        "service": "select_option",
                        "service_data": {
                            "entity_id": "input_select.s",
                            "option": "Away",
                        },
                    },
                )
            ],
        )


class StorageClient(FakeClient):
    """Answers lovelace/config per url_path and fails for missing configs."""

    def __init__(self, configs: dict, energy: dict) -> None:
        super().__init__(
            {
                "energy/get_prefs": energy,
                "lovelace/dashboards/list": [
                    {"mode": "storage", "url_path": "dashboard-home"},
                    {"mode": "storage", "url_path": "dashboard-empty"},
                    {"mode": "yaml", "url_path": "dashboard-yaml"},
                ],
            }
        )
        self.configs = configs

    async def call(self, type_: str, **payload):
        result = await super().call(type_, **payload)
        if type_ == "lovelace/config":
            if payload["url_path"] not in self.configs:
                raise HassError(
                    "lovelace/config failed: config_not_found: No config found."
                )
            return self.configs[payload["url_path"]]
        if type_ == "energy/get_prefs" and result is None:
            raise HassError("energy/get_prefs failed: not_found: No prefs")
        return result


STORAGE_ID_MAP = {"light.dad": "light.dads_room_ceiling"}


class StorageTest(unittest.IsolatedAsyncioTestCase):
    def storage_client(self) -> StorageClient:
        return StorageClient(
            configs={
                None: {"views": [{"cards": [{"entity": "sensor.outdoor"}]}]},
                "dashboard-home": {
                    "views": [
                        {
                            "cards": [
                                {"entity": "light.dad", "name": "Dad"},
                                {"entity": "light.dad_lamp"},
                            ],
                            "title": "Home",
                        }
                    ]
                },
            },
            energy={
                "device_consumption": [{"stat_consumption": "sensor.fridge"}],
                "energy_sources": [],
            },
        )

    async def test_storage_rewrite_keeps_unrelated_text(self):
        client = self.storage_client()
        with tempfile.TemporaryDirectory() as directory:
            backup_dir = pathlib.Path(directory) / "backup"
            changed = await rewrite_storage(
                client, STORAGE_ID_MAP, dry_run=False, backup_dir=backup_dir
            )
            saved = [call for call in client.calls if call[0].endswith("save")]
            self.assertEqual(changed, ["dashboard-home"])
            self.assertEqual(
                saved,
                [
                    (
                        "lovelace/config/save",
                        {
                            "config": {
                                "views": [
                                    {
                                        "cards": [
                                            {
                                                "entity": "light.dads_room_ceiling",
                                                "name": "Dad",
                                            },
                                            {"entity": "light.dad_lamp"},
                                        ],
                                        "title": "Home",
                                    }
                                ]
                            },
                            "url_path": "dashboard-home",
                        },
                    )
                ],
            )
            self.assertEqual(
                json.loads((backup_dir / "dashboard-home.json").read_text()),
                client.configs["dashboard-home"],
            )
            self.assertEqual(backup_dir.stat().st_mode & 0o777, 0o700)
            self.assertEqual(
                sorted(path.name for path in backup_dir.iterdir()),
                ["dashboard-home.json"],
            )

    async def test_storage_rewrites_ids_after_escaped_characters(self):
        client = StorageClient(
            configs={
                "dashboard-home": {
                    "type": "markdown",
                    "content": "Lights:\nlight.dad\n\tlight.dad\r\nlight.dad_lamp",
                    "e": "light.dad",
                }
            },
            energy={},
        )
        with tempfile.TemporaryDirectory() as directory:
            await rewrite_storage(
                client,
                STORAGE_ID_MAP,
                dry_run=False,
                backup_dir=pathlib.Path(directory),
            )
        saved = [
            payload["config"]
            for type_, payload in client.calls
            if type_ == "lovelace/config/save"
        ]
        self.assertEqual(
            saved,
            [
                {
                    "type": "markdown",
                    "content": (
                        "Lights:\nlight.dads_room_ceiling\n\t"
                        "light.dads_room_ceiling\r\nlight.dad_lamp"
                    ),
                    "e": "light.dads_room_ceiling",
                }
            ],
        )
        self.assertEqual(list(saved[0]), ["type", "content", "e"])

    async def test_storage_rewrites_dict_keys(self):
        client = StorageClient(
            configs={"dashboard-home": {"entities": {"light.dad": {"name": "Dad"}}}},
            energy={},
        )
        with tempfile.TemporaryDirectory() as directory:
            await rewrite_storage(
                client,
                STORAGE_ID_MAP,
                dry_run=False,
                backup_dir=pathlib.Path(directory),
            )
        self.assertIn(
            (
                "lovelace/config/save",
                {
                    "config": {
                        "entities": {"light.dads_room_ceiling": {"name": "Dad"}}
                    },
                    "url_path": "dashboard-home",
                },
            ),
            client.calls,
        )

    async def test_storage_rewrites_energy_prefs(self):
        client = self.storage_client()
        with tempfile.TemporaryDirectory() as directory:
            backup_dir = pathlib.Path(directory)
            changed = await rewrite_storage(
                client,
                {"sensor.fridge": "sensor.kitchen_fridge_energy"},
                dry_run=False,
                backup_dir=backup_dir,
            )
            self.assertEqual(changed, ["energy"])
            self.assertIn(
                (
                    "energy/save_prefs",
                    {
                        "device_consumption": [
                            {"stat_consumption": "sensor.kitchen_fridge_energy"}
                        ],
                        "energy_sources": [],
                    },
                ),
                client.calls,
            )
            self.assertTrue((backup_dir / "energy.json").exists())

    async def test_storage_skips_missing_energy_prefs(self):
        client = self.storage_client()
        client.results["energy/get_prefs"] = None
        with tempfile.TemporaryDirectory() as directory:
            changed = await rewrite_storage(
                client,
                STORAGE_ID_MAP,
                dry_run=False,
                backup_dir=pathlib.Path(directory),
            )
        self.assertEqual(changed, ["dashboard-home"])
        self.assertFalse(any(call[0] == "energy/save_prefs" for call in client.calls))

    async def test_storage_dry_run_writes_and_saves_nothing(self):
        client = self.storage_client()
        with tempfile.TemporaryDirectory() as directory:
            backup_dir = pathlib.Path(directory) / "backup"
            changed = await rewrite_storage(
                client, STORAGE_ID_MAP, dry_run=True, backup_dir=backup_dir
            )
            self.assertEqual(changed, ["dashboard-home"])
            self.assertFalse(backup_dir.exists())
        self.assertFalse(any(call[0].endswith("save") for call in client.calls))
        self.assertNotIn(
            ("lovelace/config", {"url_path": "dashboard-yaml"}), client.calls
        )


if __name__ == "__main__":
    unittest.main()
