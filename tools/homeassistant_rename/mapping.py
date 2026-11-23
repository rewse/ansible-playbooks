"""Builds the old-to-new mapping of area names, device names, and entity IDs."""

from __future__ import annotations

import csv
import dataclasses
import pathlib
import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from typing import Any, Literal, get_args

from . import rules
from .snapshot import Snapshot

Kind = Literal["area", "device", "entity"]
Source = Literal["registry", "yaml_key", "yaml_unique_id"]
Status = Literal["auto", "review", "skip"]

Slugify = Callable[[list[str]], dict[str, str]]

# YAML files whose top-level keys are the object IDs, by entity domain.
KEY_ID_FILES = {
    "input_boolean": "input_booleans.yaml",
    "input_datetime": "input_datetimes.yaml",
    "input_number": "input_numbers.yaml",
    "input_select": "input_selects.yaml",
    "script": "scripts.yaml",
}

# Object-ID prefixes that name a room in another way than the slug of its
# current area name or its area ID.
ROOM_PREFIXES = {
    "dad_s_room_": "dads_room",
    "dads_room_": "dads_room",
    "living_area_": "living_room",
    "living_room_": "living_room",
    "mom_s_room_": "bedroom",
    "moms_room_": "bedroom",
    "study_": "living_room",
}

# Prefixes for places that the rules now call by a modifier such as North.
MODIFIER_PREFIXES = frozenset({"living_area_", "study_"})

# Temperature and humidity sensors that the rules name by role in a room.
PRIMARY_THERMOMETERS = frozenset({"SwitchBot Outdoor Meter", "Thermometer"})
SECONDARY_THERMOMETERS = frozenset({"SwitchBot Meter"})
THERMOMETER = "Thermometer"

# Words that mix letters and digits but are generic names, not model numbers.
GENERIC_ALPHANUMERIC_WORDS = frozenset({"CO2", "PM2.5"})

# Brand and product words that a device name should describe instead of.
PRODUCT_WORDS = (
    "aqara",
    "aventage",
    "eufy",
    "hue",
    "regza",
    "roomba",
    "switchbot",
    "tapo",
    "vesync",
)

TOP_LEVEL_KEY = re.compile(r"^([A-Za-z0-9_]+):", re.MULTILINE)
UNIQUE_ID = re.compile(r"^\s*(?:-\s+)?unique_id:\s*(\S+?)\s*$", re.MULTILINE)
LIST_ITEM_ID = re.compile(r"^-\s+id:\s*(\S+?)\s*$", re.MULTILINE)


@dataclasses.dataclass
class Row:
    """One area, device, or entity and the name and ID it moves to."""

    room: str
    kind: Kind
    source: Source
    integration: str
    key: str
    old_name: str
    new_name: str
    old_id: str
    new_id: str
    status: Status
    note: str


@dataclasses.dataclass
class YamlSources:
    """IDs defined by the Home Assistant YAML configuration."""

    key_ids: set[str]
    unique_ids: set[str]

    def source_of(self, entity: dict[str, Any]) -> Source:
        if entity["entity_id"] in self.key_ids:
            return "yaml_key"
        if entity.get("unique_id") in self.unique_ids:
            return "yaml_unique_id"
        return "registry"


def _unquote(value: str) -> str:
    return value.strip("\"'")


def load_yaml_sources(files_dir: pathlib.Path) -> YamlSources:
    """Reads key-defined IDs and unique IDs from the Home Assistant files.

    The files use tags such as !secret and !include, so they are scanned with
    regular expressions instead of a YAML loader.
    """
    key_ids: set[str] = set()
    for domain, file_name in KEY_ID_FILES.items():
        text = (files_dir / file_name).read_text(encoding="utf-8")
        key_ids.update(f"{domain}.{key}" for key in TOP_LEVEL_KEY.findall(text))
    unique_ids: set[str] = set()
    for path in sorted(files_dir.glob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        unique_ids.update(_unquote(value) for value in UNIQUE_ID.findall(text))
        unique_ids.update(_unquote(value) for value in LIST_ITEM_ID.findall(text))
    return YamlSources(key_ids=key_ids, unique_ids=unique_ids)


def expand_name_abbreviations(name: str) -> str:
    """Spells out abbreviated words in a display name ("Max" -> "Maximum")."""
    return " ".join(
        rules.ABBREVIATIONS[word.lower()].capitalize()
        if word.lower() in rules.ABBREVIATIONS
        else word
        for word in name.split()
    )


def looks_like_model_number(name: str) -> bool:
    """Tells whether a word mixes letters and digits, as model numbers do."""
    return any(
        re.search(r"[A-Za-z]", word)
        and re.search(r"\d", word)
        and word not in GENERIC_ALPHANUMERIC_WORDS
        for word in name.split()
    )


def looks_like_product_name(name: str) -> bool:
    """Tells whether a name is a brand or product name rather than a role.

    Names that contain a known brand or product word, start with a lowercase
    letter, or contain a hyphen are typically the name the integration gave.
    """
    lowered = name.lower()
    return (
        any(word in lowered for word in PRODUCT_WORDS)
        or name[:1].islower()
        or "-" in name
    )


def device_display_name(device: dict[str, Any]) -> str:
    return device.get("name_by_user") or device.get("name") or ""


def device_integration(device: dict[str, Any]) -> str:
    identifiers = device.get("identifiers") or []
    return identifiers[0][0] if identifiers else ""


def entity_part(entity: dict[str, Any]) -> str:
    """Returns the entity's own name; "" for a main entity."""
    name = entity.get("name")
    if name is not None:
        return name
    return entity.get("original_name") or ""


def _status(reasons: list[str], changed: bool) -> Status:
    if reasons:
        return "review"
    return "auto" if changed else "skip"


class _Builder:
    def __init__(
        self, snapshot: Snapshot, yaml_sources: YamlSources, slugify: Slugify
    ) -> None:
        self.yaml_sources = yaml_sources
        self.devices = {device["id"]: device for device in snapshot.devices}
        self.area_names = {area["area_id"]: area["name"] for area in snapshot.areas}
        self.new_area_names = {
            area_id: rules.normalize_apostrophe(name)
            for area_id, name in self.area_names.items()
        }
        self.all_area_names = sorted(
            set(self.area_names.values()) | set(self.new_area_names.values())
        )
        self.areas = snapshot.areas
        self.entities = snapshot.entities
        self.devices_in_scope = {
            device_id
            for device_id, device in self.devices.items()
            if rules.in_scope(
                device, {"platform": device_integration(device)}, device.get("area_id")
            )
        }
        self.device_names = self._device_names()
        self.slugs = self._slugify_once(slugify)
        self.room_prefixes = self._room_prefixes()

    def _device_names(self) -> dict[str, tuple[str, list[str]]]:
        """Computes each device's new name and the reasons it needs review."""
        result: dict[str, tuple[str, list[str]]] = {}
        for device_id in self.devices_in_scope:
            old = device_display_name(self.devices[device_id])
            reasons: list[str] = []
            stripped = rules.strip_area(old, self.all_area_names)
            if not stripped:
                result[device_id] = (old, ["name is only the area name"])
                continue
            name, needs_review = rules.normalize_modifiers(stripped)
            if needs_review:
                reasons.append("numbered name needs a modifier")
            if looks_like_model_number(name):
                reasons.append("name looks like a model number")
            # The thermometer pair rule renames these product names by role.
            is_thermometer = name in PRIMARY_THERMOMETERS | SECONDARY_THERMOMETERS
            if not is_thermometer and looks_like_product_name(name):
                reasons.append("product name")
            result[device_id] = (name, reasons)
        self._name_thermometers(result)
        return result

    def _name_thermometers(self, names: dict[str, tuple[str, list[str]]]) -> None:
        by_room: dict[str, list[str]] = defaultdict(list)
        for device_id, (name, _) in names.items():
            if name in PRIMARY_THERMOMETERS | SECONDARY_THERMOMETERS:
                by_room[self.devices[device_id]["area_id"]].append(device_id)
        for device_ids in by_room.values():
            room_names = {names[device_id][0] for device_id in device_ids}
            paired = bool(room_names & PRIMARY_THERMOMETERS) and bool(
                room_names & SECONDARY_THERMOMETERS
            )
            for device_id in device_ids:
                name, reasons = names[device_id]
                if not paired:
                    name = THERMOMETER
                elif name in PRIMARY_THERMOMETERS:
                    name = f"{THERMOMETER} Primary"
                else:
                    name = f"{THERMOMETER} Secondary"
                names[device_id] = (name, reasons)

    def effective_area(self, entity: dict[str, Any]) -> str | None:
        if entity.get("area_id"):
            return entity["area_id"]
        device = self.devices.get(entity.get("device_id") or "")
        return device.get("area_id") if device else None

    def new_device_name(self, device_id: str) -> str:
        """Returns the device's new name, or its current one when out of scope."""
        if device_id in self.device_names:
            return self.device_names[device_id][0]
        return device_display_name(self.devices[device_id])

    def device_entity_name(self, entity: dict[str, Any], area_id: str) -> str:
        """Joins the parts Home Assistant builds a device entity's ID from."""
        device = self.devices[entity["device_id"]]
        parts = [self.new_area_names[area_id]]
        parent_id = device.get("parent_device_id")
        if parent_id is not None and parent_id in self.devices:
            parts.append(self.new_device_name(parent_id))
        parts.append(self.new_device_name(device["id"]))
        parts.append(entity_part(entity))
        return " ".join(part for part in parts if part)

    def _slugify_once(self, slugify: Slugify) -> dict[str, str]:
        names = set(self.area_names.values()) | set(self.new_area_names.values())
        for entity in self.entities:
            area_id = self.effective_area(entity)
            if area_id is None or area_id not in self.area_names:
                continue
            if entity.get("device_id") in self.devices:
                names.add(self.device_entity_name(entity, area_id))
        return slugify(sorted(names))

    def _room_prefixes(self) -> dict[str, str]:
        prefixes: dict[str, str] = {}
        for area_id, name in self.area_names.items():
            prefixes[f"{area_id}_"] = area_id
            prefixes[f"{self.slugs[name]}_"] = area_id
        prefixes.update(ROOM_PREFIXES)
        return prefixes

    def room_prefix(self, object_id: str) -> str | None:
        matches = [
            prefix for prefix in self.room_prefixes if object_id.startswith(prefix)
        ]
        return max(matches, key=len) if matches else None

    def area_rows(self) -> list[Row]:
        rows = []
        for area in self.areas:
            old = area["name"]
            new = self.new_area_names[area["area_id"]]
            rows.append(
                Row(
                    room=area["area_id"],
                    kind="area",
                    source="registry",
                    integration="",
                    key=area["area_id"],
                    old_name=old,
                    new_name=new,
                    old_id="",
                    new_id="",
                    status=_status([], old != new),
                    note="",
                )
            )
        return rows

    def device_rows(self) -> list[Row]:
        rows = []
        for device_id, device in self.devices.items():
            old = device_display_name(device)
            integration = device_integration(device)
            area_id = device.get("area_id")
            row = Row(
                room="",
                kind="device",
                source="registry",
                integration=integration,
                key=device_id,
                old_name=old,
                new_name=old,
                old_id="",
                new_id="",
                status="skip",
                note="",
            )
            if device_id in self.devices_in_scope:
                new, reasons = self.device_names[device_id]
                row.room = area_id or ""
                row.new_name = new
                row.status = _status(reasons, old != new)
                row.note = "; ".join(reasons)
            rows.append(row)
        return rows

    def entity_rows(self) -> list[Row]:
        rows = []
        for entity in self.entities:
            device = self.devices.get(entity.get("device_id") or "")
            entity_id = entity["entity_id"]
            old_name = entity_part(entity)
            row = Row(
                room="",
                kind="entity",
                source=self.yaml_sources.source_of(entity),
                integration=entity["platform"],
                key=entity_id,
                old_name=old_name,
                new_name=old_name,
                old_id=entity_id,
                new_id=entity_id,
                status="skip",
                note="",
            )
            if device is not None:
                self._fill_device_entity(row, entity)
            else:
                self._fill_own_entity(row, entity)
            rows.append(row)
        return rows

    def _fill_device_entity(self, row: Row, entity: dict[str, Any]) -> None:
        device = self.devices[entity["device_id"]]
        area_id = self.effective_area(entity)
        if area_id is None or not rules.in_scope(device, entity, area_id):
            return
        row.room = area_id
        if self._flag_unknown_area(row, area_id):
            return
        domain = row.old_id.split(".", 1)[0]
        row.new_id = f"{domain}.{self.slugs[self.device_entity_name(entity, area_id)]}"
        row.status = _status([], row.new_id != row.old_id)

    def _flag_unknown_area(self, row: Row, area_id: str) -> bool:
        """Marks a row for review when its area is not in the snapshot.

        The row keeps its name and ID, since neither can be built without the
        area's name.
        """
        if area_id in self.area_names:
            return False
        row.status = "review"
        row.note = f"unknown area {area_id}"
        return True

    def _fill_own_entity(self, row: Row, entity: dict[str, Any]) -> None:
        domain, object_id = row.old_id.split(".", 1)
        prefix = self.room_prefix(object_id)
        area_id = entity.get("area_id") or (
            self.room_prefixes[prefix] if prefix else None
        )
        if area_id is None or not rules.in_scope(None, entity, area_id):
            return
        row.room = area_id
        if self._flag_unknown_area(row, area_id):
            return
        reasons: list[str] = []
        new_prefix = f"{self.slugs[self.new_area_names[area_id]]}_"
        if prefix is None:
            reasons.append("ID does not start with a room")
            new_object_id = object_id
        else:
            if self.room_prefixes[prefix] != area_id:
                reasons.append(f"ID prefix {prefix} names another area")
            if prefix in MODIFIER_PREFIXES:
                reasons.append(f"ID prefix {prefix} needs a North or side modifier")
            new_object_id = new_prefix + object_id[len(prefix) :]
        stripped = rules.strip_area(row.old_name, self.all_area_names)
        if row.old_name and not stripped:
            reasons.append("name is only the area name")
        else:
            row.new_name = expand_name_abbreviations(stripped)
        row.room = area_id
        row.new_id = f"{domain}.{rules.expand_abbreviations(new_object_id)}"
        changed = row.new_id != row.old_id or row.new_name != row.old_name
        row.status = _status(reasons, changed)
        row.note = "; ".join(reasons)


def _flag_conflicts(rows: Iterable[Row], kind: Kind, field: str) -> None:
    groups: dict[tuple[str, str], list[Row]] = defaultdict(list)
    for row in rows:
        if row.kind != kind:
            continue
        value = getattr(row, field)
        if not value:
            continue
        # Entity IDs are global; device names only collide within a room, and
        # devices out of scope keep their names.
        if kind == "device" and not row.room:
            continue
        scope = row.room if kind == "device" else ""
        groups[(scope, value)].append(row)
    for (_, value), group in groups.items():
        if len(group) < 2:
            continue
        for row in group:
            others = ", ".join(other.key for other in group if other is not row)
            row.status = "review"
            note = f"conflict: {field} {value} also used by {others}"
            row.note = f"{row.note}; {note}" if row.note else note


KIND_ORDER = {"area": 0, "device": 1, "entity": 2}


def build_rows(
    snapshot: Snapshot, yaml_sources: YamlSources, slugify: Slugify
) -> list[Row]:
    """Maps every area, device, and entity to its name and ID under the rules.

    slugify is called once with every name whose slug the mapping needs.
    """
    builder = _Builder(snapshot, yaml_sources, slugify)
    rows = builder.area_rows() + builder.device_rows() + builder.entity_rows()
    _flag_conflicts(rows, "device", "new_name")
    _flag_conflicts(rows, "entity", "new_id")
    rows.sort(key=lambda row: (row.room, KIND_ORDER[row.kind], row.old_id, row.key))
    return rows


FIELDS = [field.name for field in dataclasses.fields(Row)]


def write_csv(rows: Iterable[Row], path: str | pathlib.Path) -> None:
    with pathlib.Path(path).open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(dataclasses.asdict(row) for row in rows)


def _literal(value: str, allowed: Any, field: str) -> Any:
    if value not in get_args(allowed):
        raise ValueError(f"invalid {field}: {value!r}")
    return value


def read_csv(path: str | pathlib.Path) -> list[Row]:
    """Reads rows back, rejecting kinds, sources, and statuses it does not know."""
    rows = []
    with pathlib.Path(path).open(encoding="utf-8", newline="") as file:
        for record in csv.DictReader(file):
            values: dict[str, Any] = dict(record)
            values["kind"] = _literal(record["kind"], Kind, "kind")
            values["source"] = _literal(record["source"], Source, "source")
            values["status"] = _literal(record["status"], Status, "status")
            rows.append(Row(**values))
    return rows
