"""Command line entry point: python -m tools.homeassistant_rename."""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import os
import pathlib
import sys

from .hass import HassClient
from .hass import slugify_all
from .mapping import build_rows
from .mapping import load_yaml_sources
from .mapping import read_csv
from .mapping import read_overrides
from .mapping import validate
from .mapping import write_csv
from .registry import apply_ops
from .registry import assign_areas
from .registry import plan_ops
from .registry import remove_orphans
from .registry import revert
from .rewrite import check
from .rewrite import count_problems
from .rewrite import entity_id_map
from .rewrite import new_problems
from .rewrite import rewrite_repo
from .rewrite import rewrite_storage
from .snapshot import Snapshot
from .snapshot import fetch_snapshot
from .values import capture
from .values import restore

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
HOMEASSISTANT_FILES = REPO_ROOT / "roles" / "homeassistant" / "files"
STATE_DIR = (
    pathlib.Path(
        os.environ.get("XDG_STATE_HOME") or pathlib.Path.home() / ".local" / "state"
    )
    / "homeassistant-rename"
)
DEFAULT_JOURNAL = STATE_DIR / "journal.jsonl"
STORAGE_BACKUP_DIR = STATE_DIR / "storage-backup"


async def connect() -> HassClient:
    """Connects with HASS_URL and HASS_TOKEN from the environment."""
    return await HassClient.connect(os.environ["HASS_URL"], os.environ["HASS_TOKEN"])


async def run_snapshot(args: argparse.Namespace) -> None:
    client = await connect()
    try:
        snapshot = await fetch_snapshot(client)
    finally:
        await client.close()
    snapshot.save(args.out)
    print(
        f"{args.out}: {len(snapshot.areas)} areas, {len(snapshot.devices)} devices, "
        f"{len(snapshot.entities)} entities, {len(snapshot.states)} states"
    )


def hass_slugify(names: list[str]) -> dict[str, str]:
    """Slugifies names with Home Assistant over one connection."""

    async def run() -> dict[str, str]:
        client = await connect()
        try:
            return await slugify_all(client, names)
        finally:
            await client.close()

    return asyncio.run(run())


def run_map(args: argparse.Namespace) -> None:
    overrides = read_overrides(args.overrides) if args.overrides else []
    rows = build_rows(
        Snapshot.load(args.snapshot),
        load_yaml_sources(args.files),
        hass_slugify,
        overrides,
    )
    write_csv(rows, args.out)
    counts = collections.Counter(row.status for row in rows)
    summary = ", ".join(f"{counts[status]} {status}" for status in sorted(counts))
    print(f"{args.out}: {len(rows)} rows ({summary})")


def run_validate(args: argparse.Namespace) -> int:
    problems = validate(read_csv(args.mapping), Snapshot.load(args.snapshot))
    for problem in problems:
        print(problem)
    print(f"{args.mapping}: {len(problems)} problems")
    return 1 if problems else 0


def run_rewrite(args: argparse.Namespace) -> None:
    rows = read_csv(args.mapping)
    if args.room is not None:
        rows = [row for row in rows if row.room == args.room]
    for path in rewrite_repo(REPO_ROOT, rows):
        print(path.relative_to(REPO_ROOT))


async def run_apply(args: argparse.Namespace) -> int:
    journal: pathlib.Path = args.journal
    if not args.dry_run and journal.exists() and journal.stat().st_size > 0:
        print(
            f"{journal} already records changes; revert them or pass --journal "
            "with a new file",
            file=sys.stderr,
        )
        return 1
    rows = read_csv(args.mapping)
    if args.room is not None:
        rows = [row for row in rows if row.room == args.room]
    client = await connect()
    try:
        snapshot = await fetch_snapshot(client)
        existing_ids = {entity["entity_id"] for entity in snapshot.entities}
        existing_ids |= set(snapshot.states)
        ops = plan_ops(rows, existing_ids, snapshot)
        await apply_ops(client, ops, journal, args.dry_run)
    finally:
        await client.close()
    if not args.dry_run:
        print(f"{journal}: {len(ops)} changes applied")
    return 0


async def run_revert(args: argparse.Namespace) -> None:
    client = await connect()
    try:
        await revert(client, args.journal)
    finally:
        await client.close()


async def run_remove_orphans(args: argparse.Namespace) -> None:
    client = await connect()
    try:
        removed = await remove_orphans(
            client, read_csv(args.mapping), dry_run=args.dry_run
        )
    finally:
        await client.close()
    for entity_id in removed:
        print(entity_id)


async def run_assign_areas(args: argparse.Namespace) -> None:
    client = await connect()
    try:
        await assign_areas(client, read_csv(args.mapping), Snapshot.load(args.snapshot))
    finally:
        await client.close()


def run_capture(args: argparse.Namespace) -> None:
    captured = capture(Snapshot.load(args.snapshot), read_csv(args.mapping))
    args.out.write_text(
        json.dumps(captured, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"{args.out}: {len(captured)} helper values")


async def run_restore(args: argparse.Namespace) -> None:
    captured = json.loads(args.captured.read_text(encoding="utf-8"))
    client = await connect()
    try:
        await restore(client, captured)
    finally:
        await client.close()


async def run_rewrite_storage(args: argparse.Namespace) -> None:
    id_map = entity_id_map(read_csv(args.mapping))
    client = await connect()
    try:
        changed = await rewrite_storage(
            client, id_map, args.dry_run, STORAGE_BACKUP_DIR
        )
    finally:
        await client.close()
    for name in changed:
        print(name)


def run_check(args: argparse.Namespace) -> int:
    snapshot = Snapshot.load(args.snapshot)
    rows = read_csv(args.mapping)
    renamed = {
        row.old_id: row.new_id
        for row in rows
        if row.kind == "entity" and row.status == "auto"
    }
    current_ids: set[str] = {entity["entity_id"] for entity in snapshot.entities}
    current_ids |= set(snapshot.states)
    valid_ids = {renamed.get(entity_id) or entity_id for entity_id in current_ids}
    valid_ids |= set(renamed.values())
    old_area_names = {
        row.old_name
        for row in rows
        if row.kind == "area" and row.old_name != row.new_name
    }
    test_ids = {
        row.old_id
        for row in rows
        if row.kind == "entity"
        and row.status == "auto"
        and row.source == "yaml_unique_id"
    }
    if args.write_baseline is not None:
        # The baseline records what is already broken before the rewrite, so
        # it treats today's IDs as valid; an old ID left after the rewrite is
        # then a new problem.
        problems = check(REPO_ROOT, current_ids, old_area_names, test_ids)
        args.write_baseline.write_text(
            json.dumps(count_problems(problems), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"{args.write_baseline}: {len(problems)} problems")
        return 0
    problems = check(REPO_ROOT, valid_ids, old_area_names, test_ids)
    if args.baseline is not None:
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        problems = new_problems(problems, baseline)
    for problem in problems:
        print(problem)
    return 1 if problems else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m tools.homeassistant_rename")
    subparsers = parser.add_subparsers(dest="command", required=True)

    applying = subparsers.add_parser(
        "apply", help="apply the auto rows of a mapping to the registries"
    )
    applying.add_argument("--dry-run", action="store_true")
    applying.add_argument("--journal", default=DEFAULT_JOURNAL, type=pathlib.Path)
    applying.add_argument("--mapping", required=True, type=pathlib.Path)
    applying.add_argument("--room")
    applying.set_defaults(handler=run_apply)

    assigning = subparsers.add_parser(
        "assign-areas",
        help="assign YAML key entities to their rooms and carry over labels",
    )
    assigning.add_argument("--mapping", required=True, type=pathlib.Path)
    assigning.add_argument(
        "--snapshot",
        help="snapshot taken before the rename, for the labels of old entries",
        required=True,
        type=pathlib.Path,
    )
    assigning.set_defaults(handler=run_assign_areas)

    capturing = subparsers.add_parser(
        "capture", help="save the values of renamed YAML key helpers to a JSON file"
    )
    capturing.add_argument("--mapping", required=True, type=pathlib.Path)
    capturing.add_argument("--out", required=True, type=pathlib.Path)
    capturing.add_argument("--snapshot", required=True, type=pathlib.Path)
    capturing.set_defaults(handler=run_capture)

    checking = subparsers.add_parser(
        "check", help="report references the rewrite cannot resolve"
    )
    checking.add_argument("--mapping", required=True, type=pathlib.Path)
    checking.add_argument("--snapshot", required=True, type=pathlib.Path)
    baselines = checking.add_mutually_exclusive_group()
    baselines.add_argument(
        "--baseline",
        help="report only problems not in this file from --write-baseline",
        type=pathlib.Path,
    )
    baselines.add_argument(
        "--write-baseline",
        help="save the problems of the repository before the rewrite",
        type=pathlib.Path,
    )
    checking.set_defaults(handler=run_check)

    mapping = subparsers.add_parser(
        "map", help="write the old-to-new naming mapping to a CSV file"
    )
    mapping.add_argument("--files", default=HOMEASSISTANT_FILES, type=pathlib.Path)
    mapping.add_argument("--out", required=True, type=pathlib.Path)
    mapping.add_argument(
        "--overrides",
        help="CSV of reviewed rows (kind,key,new_name[,new_id][,status])",
        type=pathlib.Path,
    )
    mapping.add_argument("--snapshot", required=True, type=pathlib.Path)
    mapping.set_defaults(handler=run_map)

    removing = subparsers.add_parser(
        "remove-orphans",
        help="remove registry entries of renamed YAML keys that have no state",
    )
    removing.add_argument(
        "--dry-run", action="store_true", help="list the entries without removing"
    )
    removing.add_argument("--mapping", required=True, type=pathlib.Path)
    removing.set_defaults(handler=run_remove_orphans)

    restoring = subparsers.add_parser(
        "restore", help="set helper values saved by capture on their new IDs"
    )
    restoring.add_argument("--captured", required=True, type=pathlib.Path)
    restoring.set_defaults(handler=run_restore)

    reverting = subparsers.add_parser(
        "revert", help="undo the changes recorded in an apply journal"
    )
    reverting.add_argument("--journal", default=DEFAULT_JOURNAL, type=pathlib.Path)
    reverting.set_defaults(handler=run_revert)

    snapshot = subparsers.add_parser(
        "snapshot", help="save the registries and states to a JSON file"
    )
    snapshot.add_argument("--out", required=True, type=pathlib.Path)
    snapshot.set_defaults(handler=run_snapshot)

    rewrite = subparsers.add_parser(
        "rewrite", help="rewrite the repository from the auto rows of a mapping"
    )
    rewrite.add_argument("--mapping", required=True, type=pathlib.Path)
    rewrite.add_argument("--room")
    rewrite.set_defaults(handler=run_rewrite)

    rewriting_storage = subparsers.add_parser(
        "rewrite-storage",
        help="rewrite entity IDs in storage dashboards and energy preferences",
    )
    rewriting_storage.add_argument("--dry-run", action="store_true")
    rewriting_storage.add_argument("--mapping", required=True, type=pathlib.Path)
    rewriting_storage.set_defaults(handler=run_rewrite_storage)

    validating = subparsers.add_parser(
        "validate", help="list what keeps a mapping from being applied"
    )
    validating.add_argument("--mapping", required=True, type=pathlib.Path)
    validating.add_argument("--snapshot", required=True, type=pathlib.Path)
    validating.set_defaults(handler=run_validate)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = args.handler(args)
    if asyncio.iscoroutine(result):
        result = asyncio.run(result)
    return result if isinstance(result, int) else 0


if __name__ == "__main__":
    sys.exit(main())
