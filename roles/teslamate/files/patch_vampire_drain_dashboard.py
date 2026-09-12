#!/usr/bin/env python3
"""Patch TeslaMate's Vampire Drain dashboard standby calculations."""

# Temporary workaround for https://github.com/teslamate-org/teslamate/pull/5729.
# Remove this patch after deploying an official TeslaMate Grafana image
# that contains the upstream fix.

import argparse
import copy
import json
import os
import re
import tempfile
from pathlib import Path


_DURATION_RE = re.compile(
    r"EXTRACT\s*\(\s*EPOCH\s+FROM\s+age\s*\(\s*t\.start_date\s*,\s*"
    r"lag\s*\(\s*t\.end_date\s*\)\s+OVER\s+w\s*\)\s*\)",
    re.IGNORECASE,
)
_STATE_AGGREGATE_RE = re.compile(
    r"sum\s*\(\s*age\s*\(\s*s\.end_date\s*,\s*s\.start_date\s*\)\s*\)",
    re.IGNORECASE,
)
_STATE_CONTAINMENT_RE = re.compile(
    r"v\.start_date\s*<=\s*s\.start_date\s+AND\s+"
    r"s\.end_date\s*<=\s*v\.end_date",
    re.IGNORECASE,
)

_PATCHED_DURATION = (
    "EXTRACT(EPOCH FROM (t.start_date - lag(t.end_date) OVER w))"
)
_PATCHED_AGGREGATE = """sum(LEAST(COALESCE(s.end_date, v.end_date), v.end_date)
      - GREATEST(s.start_date, v.start_date))"""
_PATCHED_CONTAINMENT = """s.start_date < v.end_date
    AND COALESCE(s.end_date, v.end_date) > v.start_date"""


def _iter_dicts(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _iter_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_dicts(child)


def _is_vampire_drain_query(query):
    query_lower = query.lower()
    return (
        "'asleep'" in query_lower
        and "'offline'" in query_lower
        and "from states" in query_lower
        and "merge" in query_lower
    )


def _validate_source_query(query):
    aggregate_count = len(_STATE_AGGREGATE_RE.findall(query))
    containment_count = len(_STATE_CONTAINMENT_RE.findall(query))
    if aggregate_count != 2 or containment_count != 2:
        raise ValueError(
            "Expected exactly two Vampire Drain state aggregates and containment "
            f"conditions, but found {aggregate_count} and {containment_count}"
        )

    duration_count = len(_DURATION_RE.findall(query))
    if duration_count != 1:
        raise ValueError(
            "Expected exactly one Vampire Drain duration expressions, "
            f"but found {duration_count}"
        )


def _is_fully_patched(query):
    return (
        not _DURATION_RE.search(query)
        and not _STATE_AGGREGATE_RE.search(query)
        and not _STATE_CONTAINMENT_RE.search(query)
        and query.count(_PATCHED_DURATION) == 1
        and query.count(
            "LEAST(COALESCE(s.end_date, v.end_date), v.end_date)"
        )
        == 2
        and query.count("GREATEST(s.start_date, v.start_date)") == 2
        and query.count("s.start_date < v.end_date") == 2
        and query.count(
            "COALESCE(s.end_date, v.end_date) > v.start_date"
        )
        == 2
    )


def _patch_query(query):
    if _is_fully_patched(query):
        return query

    _validate_source_query(query)
    query = _DURATION_RE.sub(_PATCHED_DURATION, query)
    query = _STATE_AGGREGATE_RE.sub(_PATCHED_AGGREGATE, query)
    return _STATE_CONTAINMENT_RE.sub(_PATCHED_CONTAINMENT, query)


def patch_dashboard(dashboard):
    """Return a patched dashboard, failing closed on an unexpected schema."""
    patched = copy.deepcopy(dashboard)
    targets = []
    for node in _iter_dicts(patched):
        query = node.get("rawSql")
        if isinstance(query, str) and _is_vampire_drain_query(query):
            targets.append(node)

    if len(targets) != 1:
        raise ValueError(
            "Expected exactly one Vampire Drain query, "
            f"but found {len(targets)}"
        )

    targets[0]["rawSql"] = _patch_query(targets[0]["rawSql"])
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
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    with args.input.open(encoding="utf-8") as input_file:
        dashboard = json.load(input_file)
    patched = patch_dashboard(dashboard)
    changed = write_dashboard(args.output, patched)
    print("changed" if changed else "unchanged")


if __name__ == "__main__":
    main()
