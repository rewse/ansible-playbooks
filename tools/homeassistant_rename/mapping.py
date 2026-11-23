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


@dataclasses.dataclass(frozen=True)
class Override:
    """A reviewed name, ID, or status that replaces the generated one.

    new_name is the area or device name, or the entity's own name ("" for a
    main entity). new_id pins an entity's ID; "" keeps the generated one.
    status, when given, is final except for conflicts.
    """

    kind: Kind
    key: str
    new_name: str
    new_id: str = ""
    status: Status | None = None


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
        self,
        snapshot: Snapshot,
        yaml_sources: YamlSources,
        slugify: Slugify,
        overrides: Iterable[Override],
    ) -> None:
        self.yaml_sources = yaml_sources
        self.devices = {device["id"]: device for device in snapshot.devices}
        self.area_names = {area["area_id"]: area["name"] for area in snapshot.areas}
        self.entities = snapshot.entities
        self.overrides = self._index_overrides(overrides)
        self.used_overrides: set[tuple[Kind, str]] = set()
        self.new_area_names = {
            area_id: self._override_name("area", area_id)
            or rules.normalize_apostrophe(name)
            for area_id, name in self.area_names.items()
        }
        self.all_area_names = sorted(
            set(self.area_names.values()) | set(self.new_area_names.values())
        )
        self.areas = snapshot.areas
        self.devices_in_scope = {
            device_id
            for device_id, device in self.devices.items()
            if rules.in_scope(
                device, {"platform": device_integration(device)}, device.get("area_id")
            )
        }
        self.device_names = self._device_names()
        # Filled by build_rows once device conflicts are known.
        self.device_statuses: dict[str, Status] = {}
        self.slugs = self._slugify_once(slugify)
        self.room_prefixes = self._room_prefixes()

    def _index_overrides(
        self, overrides: Iterable[Override]
    ) -> dict[tuple[Kind, str], Override]:
        known: dict[Kind, set[str]] = {
            "area": set(self.area_names),
            "device": set(self.devices),
            "entity": {entity["entity_id"] for entity in self.entities},
        }
        result: dict[tuple[Kind, str], Override] = {}
        for override in overrides:
            if override.key not in known[override.kind]:
                raise ValueError(f"override for unknown {override.kind} {override.key}")
            if override.kind != "entity" and override.new_id:
                raise ValueError(f"override for {override.key} sets new_id")
            if override.kind != "entity" and not override.new_name:
                raise ValueError(f"override for {override.key} has no new_name")
            domain = override.key.split(".", 1)[0]
            if override.new_id and not override.new_id.startswith(f"{domain}."):
                raise ValueError(
                    f"override for {override.key} moves it to another domain"
                )
            result[(override.kind, override.key)] = override
        return result

    def override(self, kind: Kind, key: str) -> Override | None:
        """Returns the override of a row and records that it was used."""
        override = self.overrides.get((kind, key))
        if override is not None:
            self.used_overrides.add((kind, key))
        return override

    def _override_name(self, kind: Kind, key: str) -> str | None:
        override = self.override(kind, key)
        return override.new_name if override else None

    def unused_overrides(self) -> list[str]:
        return sorted(
            f"{kind} {key}"
            for kind, key in self.overrides
            if (kind, key) not in self.used_overrides
        )

    def _device_names(self) -> dict[str, tuple[str, list[str]]]:
        """Computes each device's new name and the reasons it needs review.

        An override replaces the generated name and is checked the same way.
        """
        result: dict[str, tuple[str, list[str]]] = {}
        for device_id in self.devices_in_scope:
            old = device_display_name(self.devices[device_id])
            stripped = rules.strip_area(old, self.all_area_names)
            if not stripped:
                result[device_id] = (old, ["name is only the area name"])
                continue
            name, _ = rules.normalize_modifiers(stripped)
            # The thermometer pair rule renames these product names by role.
            is_thermometer = name in PRIMARY_THERMOMETERS | SECONDARY_THERMOMETERS
            result[device_id] = (name, self.device_name_reasons(name, is_thermometer))
        self._name_thermometers(result)
        for device_id in self.devices_in_scope:
            name = self._override_name("device", device_id)
            if name is not None:
                result[device_id] = (name, self.device_name_reasons(name))
        return result

    def device_name_reasons(self, name: str, is_thermometer: bool = False) -> list[str]:
        reasons: list[str] = []
        if any(word.isdigit() for word in name.split()):
            reasons.append("numbered name needs a modifier")
        if looks_like_model_number(name):
            reasons.append("name looks like a model number")
        if not is_thermometer and looks_like_product_name(name):
            reasons.append("product name")
        return reasons + self.name_reasons(name)

    def name_reasons(self, name: str) -> list[str]:
        """Lists the parts of a new name that the rules leave to a person."""
        reasons = [
            f"direction abbreviation {word}"
            for word in rules.direction_abbreviations(name)
        ]
        reasons += [
            f"area name {area} in name"
            for area in rules.area_names_in(name, self.all_area_names)
        ]
        return reasons

    @staticmethod
    def id_reasons(entity_id: str) -> list[str]:
        """Flags a new ID with a word repeated, such as camera_camera_fps."""
        run = rules.repeated_tokens(entity_id.split(".", 1)[1])
        return [f"repeated {run} in ID"] if run else []

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
        parts.append(self.entity_name(entity))
        return " ".join(part for part in parts if part)

    def entity_name(self, entity: dict[str, Any]) -> str:
        """Returns the entity's new own name: its override, else its current one."""
        override = self.overrides.get(("entity", entity["entity_id"]))
        return override.new_name if override else entity_part(entity)

    def device_under_review(self, device: dict[str, Any]) -> bool:
        """Tells whether the device or its parent, whose names build IDs, is review."""
        device_ids = [device["id"], device.get("parent_device_id")]
        return any(
            self.device_statuses.get(device_id or "") == "review"
            for device_id in device_ids
        )

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
            row = Row(
                room=area["area_id"],
                kind="area",
                source="registry",
                integration="",
                key=area["area_id"],
                old_name=old,
                new_name=new,
                old_id="",
                new_id="",
                status="skip",
                note="",
            )
            _finish(row, [], old != new, self.override("area", row.key))
            rows.append(row)
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
                _finish(row, reasons, old != new, self.override("device", device_id))
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
        override = self.override("entity", row.key)
        domain = row.old_id.split(".", 1)[0]
        row.new_name = self.entity_name(entity)
        row.new_id = (override.new_id if override else "") or (
            f"{domain}.{self.slugs[self.device_entity_name(entity, area_id)]}"
        )
        changed = row.new_id != row.old_id or row.new_name != row.old_name
        reasons = self.changed_reasons(row) if changed else []
        # The ID is built from the device's name, which is not settled yet.
        if override is None and self.device_under_review(device):
            reasons.insert(0, "device under review")
        _finish(row, reasons, changed, override)

    def changed_reasons(self, row: Row) -> list[str]:
        """Flags the new name and ID of an entity row that changes."""
        return self.name_reasons(row.new_name) + self.id_reasons(row.new_id)

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
        override = self.override("entity", row.key)
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
        if override is not None and override.new_id:
            # The reasons above are about the generated ID, which is replaced.
            reasons = []
            row.new_id = override.new_id
        else:
            row.new_id = f"{domain}.{rules.expand_abbreviations(new_object_id)}"
        stripped = rules.strip_area(row.old_name, self.all_area_names)
        if override is not None:
            row.new_name = override.new_name
        elif row.old_name and not stripped:
            reasons.append("name is only the area name")
        else:
            row.new_name = expand_name_abbreviations(stripped)
        changed = row.new_id != row.old_id or row.new_name != row.old_name
        if changed:
            reasons += self.changed_reasons(row)
        _finish(row, reasons, changed, override)


def _finish(
    row: Row, reasons: list[str], changed: bool, override: Override | None
) -> None:
    """Sets a row's status: the override's when it has one, else the rules'."""
    if override is not None and override.status is not None:
        row.status = override.status
        row.note = "status set by override"
        return
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
    snapshot: Snapshot,
    yaml_sources: YamlSources,
    slugify: Slugify,
    overrides: Iterable[Override] = (),
) -> list[Row]:
    """Maps every area, device, and entity to its name and ID under the rules.

    slugify is called once with every name whose slug the mapping needs.
    overrides replace generated names, IDs, and statuses before the entity IDs
    and conflicts are computed; one that matches no row in scope is an error.
    """
    builder = _Builder(snapshot, yaml_sources, slugify, overrides)
    devices = builder.device_rows()
    _flag_conflicts(devices, "device", "new_name")
    builder.device_statuses = {row.key: row.status for row in devices}
    entities = builder.entity_rows()
    _flag_conflicts(entities, "entity", "new_id")
    rows = builder.area_rows() + devices + entities
    unused = builder.unused_overrides()
    if unused:
        raise ValueError(f"overrides match no row in scope: {', '.join(unused)}")
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


OVERRIDE_REQUIRED_FIELDS = ("kind", "key", "new_name")


def read_overrides(path: str | pathlib.Path) -> list[Override]:
    """Reads an overrides CSV with kind, key, new_name, and optional new_id, status.

    Rows with the mapping's other columns are accepted, so reviewed rows can be
    copied from a mapping CSV as they are.
    """
    overrides: list[Override] = []
    seen: set[tuple[str, str]] = set()
    with pathlib.Path(path).open(encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        missing = [
            field
            for field in OVERRIDE_REQUIRED_FIELDS
            if field not in (reader.fieldnames or [])
        ]
        if missing:
            raise ValueError(f"{path}: missing columns {', '.join(missing)}")
        for record in reader:
            kind = _literal(record["kind"], Kind, "kind")
            key = record["key"]
            if (kind, key) in seen:
                raise ValueError(f"{path}: more than one override for {kind} {key}")
            seen.add((kind, key))
            status = record.get("status") or ""
            overrides.append(
                Override(
                    kind=kind,
                    key=key,
                    new_name=record["new_name"] or "",
                    new_id=record.get("new_id") or "",
                    status=_literal(status, Status, "status") if status else None,
                )
            )
    return overrides


def validate(rows: list[Row], snapshot: Snapshot) -> list[str]:
    """Lists what keeps a mapping from being applied.

    Reports rows still under review, new IDs shared by auto rows, and new IDs
    held by an entity that the mapping does not move away.
    """
    problems = [
        f"{row.key}: still review" + (f" ({row.note})" if row.note else "")
        for row in rows
        if row.status == "review"
    ]
    auto = [row for row in rows if row.kind == "entity" and row.status == "auto"]
    by_new_id: dict[str, list[str]] = defaultdict(list)
    for row in auto:
        by_new_id[row.new_id].append(row.old_id)
    problems += [
        f"{new_id}: new ID of {', '.join(sorted(old_ids))}"
        for new_id, old_ids in sorted(by_new_id.items())
        if len(old_ids) > 1
    ]
    moved = [row for row in auto if row.old_id != row.new_id]
    vacated = {row.old_id for row in moved}
    existing = {entity["entity_id"] for entity in snapshot.entities}
    existing |= set(snapshot.states)
    problems += [
        f"{row.old_id}: new ID {row.new_id} is held by an entity that is not renamed"
        for row in moved
        if row.new_id in existing and row.new_id not in vacated
    ]
    return problems
