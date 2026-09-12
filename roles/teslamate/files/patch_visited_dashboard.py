#!/usr/bin/env python3
"""Patch TeslaMate's Visited dashboard with a private-geofence filter."""

import argparse
import copy
import json
import os
import re
import tempfile
from pathlib import Path


FILTER_MARKER = "-- Ansible-managed private geofence filter"
_FROM_POSITIONS_RE = re.compile(
    r"(?im)(\bFROM\s+)positions(?:\s+(?:AS\s+)?([A-Za-z_][A-Za-z0-9_]*))?"
    r"(?=\s+WHERE\b)"
)
_FROM_UNIONED_POSITIONS_RE = re.compile(
    r"(?im)(\bFROM\s+)unioned_positions"
    r"(?:\s+(?:AS\s+)?([A-Za-z_][A-Za-z0-9_]*))?"
    r"(?=\s+GROUP\s+BY\b)"
)
_QUERY_BOUNDARY_RE = re.compile(r"(?im)^\s*(?:GROUP\s+BY|ORDER\s+BY)\b")


def _sql_literal(value):
    return "'" + value.replace("'", "''") + "'"


def _iter_dicts(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _iter_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_dicts(child)


def _route_source_match(query):
    return _FROM_UNIONED_POSITIONS_RE.search(query) or _FROM_POSITIONS_RE.search(query)


def _is_positions_target(panel, target):
    query = target.get("rawSql", "")
    query_lower = query.lower()
    return (
        panel.get("type") == "geomap"
        and "latitude" in query_lower
        and "longitude" in query_lower
        and _route_source_match(query) is not None
    )


def _patch_query(query, geofence_name):
    if FILTER_MARKER in query:
        return query

    source_match = _route_source_match(query)
    if source_match is None:
        raise ValueError("Could not identify the route source in the dashboard query")

    source_name = source_match.group(0).strip().split()[1]
    alias = source_match.group(2) or "p"
    if source_match.group(2) is None:
        replacement = source_match.group(1) + source_name + " " + alias
        query = query[: source_match.start()] + replacement + query[source_match.end() :]
        source_end = source_match.start() + len(replacement)
    else:
        source_end = source_match.end()

    boundary_match = _QUERY_BOUNDARY_RE.search(query, source_end)
    if boundary_match is None:
        raise ValueError("Could not identify the query boundary after the route source")

    filter_keyword = "WHERE" if source_name.lower() == "unioned_positions" else "AND"
    filter_sql = f"""  {FILTER_MARKER}
  {filter_keyword} NOT EXISTS (
    SELECT 1
    FROM geofences g
    WHERE g.name = {_sql_literal(geofence_name)}
      AND earth_box(
            ll_to_earth(g.latitude, g.longitude),
            g.radius
          ) @> ll_to_earth({alias}.latitude, {alias}.longitude)
      AND earth_distance(
            ll_to_earth(g.latitude, g.longitude),
            ll_to_earth({alias}.latitude, {alias}.longitude)
          ) < g.radius
  )
"""
    return (
        query[: boundary_match.start()]
        + filter_sql
        + query[boundary_match.start() :]
    )


def patch_dashboard(dashboard, geofence_name):
    """Return a patched dashboard, failing closed on an unexpected schema."""
    patched = copy.deepcopy(dashboard)
    targets = []
    for node in _iter_dicts(patched):
        if "targets" not in node:
            continue
        for target in node.get("targets", []):
            if _is_positions_target(node, target):
                targets.append(target)

    if len(targets) != 1:
        raise ValueError(
            "Expected exactly one Visited positions query, "
            f"but found {len(targets)}"
        )

    targets[0]["rawSql"] = _patch_query(targets[0]["rawSql"], geofence_name)
    return patched


def write_dashboard(output_path, dashboard):
    """Atomically write dashboard JSON and return whether content changed."""
    output_path = Path(output_path)
    content = json.dumps(dashboard, ensure_ascii=False, indent=2) + "\n"
    if output_path.exists() and output_path.read_text(encoding="utf-8") == content:
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=output_path.parent, prefix=output_path.name + "."
    )
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as temporary_file:
            temporary_file.write(content)
        os.chmod(temporary_name, 0o644)
        os.replace(temporary_name, output_path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--geofence", required=True)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    with args.input.open(encoding="utf-8") as input_file:
        dashboard = json.load(input_file)
    patched = patch_dashboard(dashboard, args.geofence)
    changed = write_dashboard(args.output, patched)
    print("changed" if changed else "unchanged")


if __name__ == "__main__":
    main()
