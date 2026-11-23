"""Rewrites entity references in the repository from the naming mapping.

The Home Assistant files use tags such as !secret and !include and carry
comments, so every edit works on the text line by line instead of loading and
dumping YAML.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
from collections.abc import Iterable, Mapping
from typing import Any

from .hass import HassError
from .mapping import KEY_ID_FILES
from .mapping import Row
from .registry import Client

# A YAML `id:` or `unique_id:` key. Its value is an opaque key whose history
# Home Assistant keeps, so the value is never rewritten.
ID_LINE = re.compile(r"^\s*(?:-\s+)?(?:unique_id|id):")
UNIQUE_ID_VALUE = re.compile(r"^(\s*)(-\s+)?(?:unique_id|id):\s*(\S+?)\s*$")
NAME_KEY = re.compile(r"^(name|alias):")
TOP_LEVEL_KEY = re.compile(r"^([A-Za-z0-9_]+):")

# An ID starts at the start of a line, after a character that cannot be part of
# an ID, or after `states.`; it ends before a character that cannot be part of
# an ID.
ID_START = r"(?:(?<=states\.)|(?<![a-z0-9_.]))"
ID_END = r"(?![a-z0-9_])"

# Entity domains whose IDs check() verifies. date, datetime, text, and time are
# left out because they clash with Python and Jinja attribute access such as
# datetime.datetime and text.strip; notify is left out because its references
# are actions such as notify.tats_devices.
ENTITY_DOMAINS = (
    "alarm_control_panel",
    "automation",
    "binary_sensor",
    "button",
    "calendar",
    "camera",
    "climate",
    "counter",
    "cover",
    "device_tracker",
    "event",
    "fan",
    "humidifier",
    "image",
    "input_boolean",
    "input_button",
    "input_datetime",
    "input_number",
    "input_select",
    "input_text",
    "lawn_mower",
    "light",
    "lock",
    "media_player",
    "number",
    "person",
    "remote",
    "scene",
    "schedule",
    "script",
    "select",
    "sensor",
    "siren",
    "sun",
    "switch",
    "timer",
    "todo",
    "update",
    "vacuum",
    "valve",
    "water_heater",
    "weather",
    "zone",
)

# Action names that share the domain.object form with entity IDs. check()
# ignores a reference whose object is one of these, in any entity domain.
SERVICES = frozenset(
    {
        "alarm_arm_away",
        "alarm_arm_home",
        "alarm_arm_night",
        "alarm_arm_vacation",
        "alarm_disarm",
        "alarm_trigger",
        "apply",
        "close_cover",
        "decrement",
        "increment",
        "lock",
        "media_pause",
        "media_play",
        "media_stop",
        "open",
        "open_cover",
        "pause",
        "play_media",
        "press",
        "reload",
        "reset",
        "return_to_base",
        "select_next",
        "select_option",
        "select_previous",
        "select_source",
        "send_command",
        "set_cover_position",
        "set_datetime",
        "set_fan_mode",
        "set_humidity",
        "set_hvac_mode",
        "set_percentage",
        "set_preset_mode",
        "set_temperature",
        "set_value",
        "start",
        "stop",
        "stop_cover",
        "toggle",
        "trigger",
        "turn_off",
        "turn_on",
        "unlock",
        "volume_mute",
        "volume_set",
    }
)

ENTITY_REFERENCE = re.compile(
    ID_START + r"(" + "|".join(ENTITY_DOMAINS) + r")\.([a-z0-9_]+)" + ID_END
)

# Jinja that builds an ID from parts, such as 'sensor.' ~ room or ~ '_x'.
CONCATENATION = re.compile(r"""['"]\^?[a-z_]+\\?\.['"]\s*~|~\s*['"]_""")

RENAME_TEST = "test_homeassistant_rename.py"


def _id_pattern(ids: Iterable[str]) -> re.Pattern[str]:
    alternatives = "|".join(
        re.escape(entity_id) for entity_id in sorted(ids, key=len, reverse=True)
    )
    return re.compile(ID_START + r"(" + alternatives + r")" + ID_END)


def rewrite_text(text: str, id_map: Mapping[str, str]) -> str:
    """Replaces entity IDs in one pass, keeping `id:` and `unique_id:` values."""
    if not id_map:
        return text
    pattern = _id_pattern(id_map)
    lines = text.splitlines(keepends=True)
    return "".join(
        line
        if ID_LINE.match(line)
        else pattern.sub(lambda match: id_map[match.group(1)], line)
        for line in lines
    )


def _quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _is_content(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith("#")


def _set_name(lines: list[str], index: int, column: int, name: str) -> None:
    line = lines[index]
    match = NAME_KEY.match(line[column:])
    assert match is not None
    newline = "\n" if line.endswith("\n") else ""
    lines[index] = f"{line[:column]}{match.group(1)}: {_quote(name)}{newline}"


def _find_name(lines: list[str], start: int, end: int, column: int) -> int | None:
    """Returns the line of the `name:` or `alias:` key at column, if any."""
    for index in range(start, end):
        line = lines[index]
        if not _is_content(line):
            continue
        at_column = line[:column].strip(" -") == "" and len(line) > column
        if at_column and line[column] != " " and NAME_KEY.match(line[column:]):
            return index
    return None


def rewrite_yaml_keys(text: str, key_map: Mapping[str, tuple[str, str]]) -> str:
    """Renames top-level keys and sets the `name:` or `alias:` of their blocks.

    key_map maps an old object ID to its new object ID and new name. A block
    without either key gets a `name:` line after its key.
    """
    lines = text.splitlines(keepends=True)
    index = 0
    while index < len(lines):
        match = TOP_LEVEL_KEY.match(lines[index])
        if match is None or match.group(1) not in key_map:
            index += 1
            continue
        new_key, new_name = key_map[match.group(1)]
        lines[index] = new_key + lines[index][match.end(1) :]
        end = index + 1
        while end < len(lines) and not (
            lines[end].strip() and _indent(lines[end]) == 0
        ):
            end += 1
        children = [line for line in lines[index + 1 : end] if _is_content(line)]
        column = _indent(children[0]) if children else 2
        name_index = _find_name(lines, index + 1, end, column)
        if name_index is not None:
            _set_name(lines, name_index, column, new_name)
        else:
            lines.insert(index + 1, f"{' ' * column}name: {_quote(new_name)}\n")
        index = end
    return "".join(lines)


def _item_bounds(
    lines: list[str], index: int, column: int, is_item: bool
) -> tuple[int, int]:
    """Returns the lines of the mapping whose keys start at column."""
    start = index
    if not is_item:
        start = 0
        for back in range(index - 1, -1, -1):
            line = lines[back]
            if not _is_content(line) or _indent(line) >= column:
                continue
            item = re.match(r"^(\s*-\s+)", line)
            start = back if item and len(item.group(1)) == column else back + 1
            break
    end = len(lines)
    for forward in range(index + 1, len(lines)):
        line = lines[forward]
        if _is_content(line) and _indent(line) < column:
            end = forward
            break
    return start, end


def rewrite_yaml_names(text: str, name_map: Mapping[str, str]) -> str:
    """Sets the `name:` or `alias:` of blocks whose `unique_id` or `id` matches.

    name_map maps a unique ID to its new name. The ID values stay as they are.
    """
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        match = UNIQUE_ID_VALUE.match(line.rstrip("\n"))
        if match is None:
            continue
        unique_id = match.group(3).strip("\"'")
        if unique_id not in name_map:
            continue
        column = len(match.group(1)) + len(match.group(2) or "")
        start, end = _item_bounds(lines, index, column, match.group(2) is not None)
        name_index = _find_name(lines, start, end, column)
        if name_index is not None:
            _set_name(lines, name_index, column, name_map[unique_id])
    return "".join(lines)


def _homeassistant_files(root: pathlib.Path) -> list[pathlib.Path]:
    role = root / "roles" / "homeassistant"
    return sorted(
        path
        for directory in (role / "files", role / "templates")
        if directory.is_dir()
        for path in directory.iterdir()
        if path.is_file()
    )


def _test_files(root: pathlib.Path) -> list[pathlib.Path]:
    role_tests = root / "roles" / "homeassistant" / "tests"
    paths = sorted(role_tests.glob("*.yml")) if role_tests.is_dir() else []
    paths += sorted(
        path
        for path in (root / "tests").glob("test_homeassistant_*.py")
        if path.name != RENAME_TEST
    )
    return paths


def _changed_entities(rows: Iterable[Row]) -> list[Row]:
    return [row for row in rows if row.kind == "entity" and row.status == "auto"]


def entity_id_map(rows: Iterable[Row]) -> dict[str, str]:
    """Maps the old ID of each auto entity row to its new ID when they differ."""
    return {
        row.old_id: row.new_id
        for row in _changed_entities(rows)
        if row.old_id != row.new_id
    }


def rewrite_repo(root: pathlib.Path, rows: list[Row]) -> list[pathlib.Path]:
    """Applies the auto rows to the Home Assistant files and tests.

    Tests look up automations and template entities by their unique IDs, so
    the IDs of yaml_unique_id rows stay as they are in test files.
    """
    entities = _changed_entities(rows)
    id_map = entity_id_map(rows)
    test_id_map = {
        row.old_id: row.new_id
        for row in entities
        if row.old_id != row.new_id and row.source != "yaml_unique_id"
    }
    key_maps: dict[str, dict[str, tuple[str, str]]] = {}
    for row in entities:
        if row.source != "yaml_key":
            continue
        domain, old_key = row.old_id.split(".", 1)
        new_key = row.new_id.split(".", 1)[1]
        key_maps.setdefault(KEY_ID_FILES[domain], {})[old_key] = (new_key, row.new_name)
    name_map = {
        row.old_id: row.new_name
        for row in entities
        if row.source == "yaml_unique_id" and row.new_name != row.old_name
    }

    changed = []
    for path in _homeassistant_files(root):
        text = path.read_text(encoding="utf-8")
        new_text = text
        if path.name in key_maps and path.parent.name == "files":
            new_text = rewrite_yaml_keys(new_text, key_maps[path.name])
        new_text = rewrite_yaml_names(new_text, name_map)
        new_text = rewrite_text(new_text, id_map)
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")
            changed.append(path)
    for path in _test_files(root):
        text = path.read_text(encoding="utf-8")
        new_text = rewrite_text(text, test_id_map)
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")
            changed.append(path)
    return changed


def check(
    root: pathlib.Path,
    valid_ids: set[str],
    old_area_names: set[str],
    test_ids: frozenset[str] | set[str] = frozenset(),
) -> list[str]:
    """Lists references the rewrite left for a person to resolve.

    Reports entity IDs not in valid_ids, IDs built by string concatenation,
    and old area names. test_ids are also accepted in test files, where the
    unique IDs of yaml_unique_id rows stay as lookup keys.
    """
    test_files = set(_test_files(root))
    problems = []
    for path in _homeassistant_files(root) + sorted(test_files):
        accepted = valid_ids | set(test_ids) if path in test_files else valid_ids
        relative = path.relative_to(root).as_posix()
        lines = path.read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(lines, start=1):
            where = f"{relative}:{number}"
            if not ID_LINE.match(line):
                for match in ENTITY_REFERENCE.finditer(line):
                    entity_id = match.group(0)
                    if match.group(2) not in SERVICES and entity_id not in accepted:
                        problems.append(f"{where}: unknown entity ID {entity_id}")
            if CONCATENATION.search(line):
                problems.append(f"{where}: entity ID built by concatenation")
            for name in sorted(old_area_names):
                if name in line:
                    problems.append(f"{where}: old area name {name}")
    return problems


DEFAULT_DASHBOARD = "lovelace"
ENERGY = "energy"


def _rewrite_value(value: Any, id_map: Mapping[str, str]) -> Any:
    """Returns value with IDs rewritten in every string and dict key.

    Strings are rewritten decoded, so an ID after a newline or tab inside a
    string is matched; dict key order is kept.
    """
    if isinstance(value, str):
        return rewrite_text(value, id_map)
    if isinstance(value, dict):
        return {
            rewrite_text(key, id_map): _rewrite_value(item, id_map)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_rewrite_value(item, id_map) for item in value]
    return value


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _back_up(backup_dir: pathlib.Path, name: str, text: str) -> None:
    """Writes the original JSON once, keeping the first backup on reruns."""
    backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    backup_dir.chmod(0o700)
    path = backup_dir / f"{name}.json"
    if path.exists():
        return
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as backup:
        backup.write(text + "\n")


async def _read(
    client: Client, type_: str, missing_code: str, **payload: Any
) -> dict[str, Any] | None:
    """Returns the result of type_, or None when it fails with missing_code."""
    try:
        return await client.call(type_, **payload)
    except HassError as error:
        if f": {missing_code}:" in str(error):
            return None
        raise


async def rewrite_storage(
    client: Client,
    id_map: Mapping[str, str],
    dry_run: bool,
    backup_dir: pathlib.Path,
) -> list[str]:
    """Rewrites entity IDs in storage dashboards and the energy preferences.

    Each changed configuration is backed up to backup_dir/<name>.json before
    it is saved; the default dashboard is named lovelace. A dry run backs up
    and saves nothing. Returns the names of the changed configurations.
    """
    dashboards = await client.call("lovelace/dashboards/list")
    url_paths: list[str | None] = [None]
    url_paths += [
        dashboard["url_path"]
        for dashboard in dashboards
        if dashboard.get("mode") == "storage"
    ]
    changed = []
    for url_path in url_paths:
        config = await _read(
            client, "lovelace/config", "config_not_found", url_path=url_path
        )
        if config is None:
            continue
        new_config = _rewrite_value(config, id_map)
        if new_config == config:
            continue
        name = url_path or DEFAULT_DASHBOARD
        changed.append(name)
        if not dry_run:
            _back_up(backup_dir, name, _dump(config))
            await client.call(
                "lovelace/config/save", url_path=url_path, config=new_config
            )
    # Home Assistant answers not_found until the energy dashboard is set up.
    prefs = await _read(client, "energy/get_prefs", "not_found")
    if prefs is None:
        return changed
    new_prefs = _rewrite_value(prefs, id_map)
    if new_prefs != prefs:
        changed.append(ENERGY)
        if not dry_run:
            _back_up(backup_dir, ENERGY, _dump(prefs))
            await client.call("energy/save_prefs", **new_prefs)
    return changed
