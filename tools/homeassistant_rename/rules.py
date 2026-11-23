"""Naming rules for Home Assistant device names and entity IDs."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

ABBREVIATIONS = {
    "diff": "difference",
    "max": "maximum",
    "min": "minimum",
    "temp": "temperature",
}

DIRECTIONS = {
    "E": "East",
    "N": "North",
    "NE": "Northeast",
    "NW": "Northwest",
    "S": "South",
    "SE": "Southeast",
    "SW": "Southwest",
    "W": "West",
}

# Modifiers that some names carry in front; the rules place them last.
LEADING_MODIFIERS = frozenset(
    {"Bottom", "Center", "Entrance", "Left", "Middle", "Right", "Top"}
)

# "Study" names the desk side of the living room, which the rules call North.
STUDY = "Study"
STUDY_MODIFIER = "North"

# Integrations whose names are managed elsewhere or are not tied to a room.
OUT_OF_SCOPE_PLATFORMS = frozenset({"backup", "hassio", "sun", "unifi", "unifiprotect"})


def normalize_apostrophe(name: str) -> str:
    """Replaces the typographic apostrophe (U+2019) with the ASCII one."""
    return name.replace("\u2019", "'")


def strip_area(name: str, area_names: Iterable[str]) -> str:
    """Removes a leading area name and the whitespace after it.

    Apostrophes are compared after normalization, so "Dad’s Room" and
    "Dad's Room" match each other. A name equal to an area name returns "".
    """
    normalized = normalize_apostrophe(name)
    for area in sorted(
        (normalize_apostrophe(area) for area in area_names), key=len, reverse=True
    ):
        if normalized == area:
            return ""
        if normalized.startswith(area + " "):
            # The normalization keeps the length, so the offset is valid in name.
            return name[len(area) :].lstrip()
    return name


def normalize_modifiers(name: str) -> tuple[str, bool]:
    """Moves modifiers to the end of the name and spells out directions.

    Returns the new name and whether it needs review. A numbered name such as
    "Floor Heater 2" needs a modifier chosen by hand, so it is flagged.
    """
    words = name.split()
    if len(words) > 1 and words[0] == STUDY:
        words = [*words[1:], STUDY_MODIFIER]
    elif len(words) > 1 and words[0] in LEADING_MODIFIERS:
        words = [*words[1:], words[0]]
    if words:
        words[-1] = DIRECTIONS.get(words[-1], words[-1])
    needs_review = any(word.isdigit() for word in words)
    return " ".join(words), needs_review


def expand_abbreviations(object_id: str) -> str:
    """Spells out abbreviations that appear as whole "_"-separated tokens."""
    return "_".join(ABBREVIATIONS.get(token, token) for token in object_id.split("_"))


def direction_abbreviations(name: str) -> list[str]:
    """Lists the words of name that are abbreviated directions such as "N"."""
    return [word for word in name.split() if word in DIRECTIONS]


def area_names_in(name: str, area_names: Iterable[str]) -> list[str]:
    """Lists the area names that appear as whole words anywhere in name.

    Apostrophes are normalized and case is ignored, so "Dad’s Room" and
    "dad's room" match each other. The names are returned normalized.
    """
    normalized = normalize_apostrophe(name)
    found = []
    for area in sorted({normalize_apostrophe(area) for area in area_names}):
        pattern = r"(?<!\w)" + re.escape(area) + r"(?!\w)"
        if re.search(pattern, normalized, re.IGNORECASE):
            found.append(area)
    return found


def repeated_tokens(object_id: str) -> str | None:
    """Returns the first token or token pair that repeats right after itself.

    Runs of digits are left out, since numbered IDs such as x_1_1 are not
    duplicated words.
    """
    tokens = object_id.split("_")
    for size in (1, 2):
        for start in range(len(tokens) - 2 * size + 1):
            run = tokens[start : start + size]
            if run == tokens[start + size : start + 2 * size] and not all(
                token.isdigit() for token in run
            ):
                return "_".join(run)
    return None


def in_scope(
    device: dict[str, Any] | None, entity: dict[str, Any], area_id: str | None
) -> bool:
    """Tells whether the migration renames an entity and its device.

    area_id is the effective area: the entity's own, else its device's. Only
    entities in an area are renamed, which leaves out devices without an area
    and people and device trackers that are not placed in a room. The device is
    accepted for callers' convenience; its area is already folded into area_id.
    """
    _ = device
    if entity["platform"] in OUT_OF_SCOPE_PLATFORMS:
        return False
    return area_id is not None
