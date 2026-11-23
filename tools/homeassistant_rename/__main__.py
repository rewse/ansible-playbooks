"""Command line entry point: python -m tools.homeassistant_rename."""

from __future__ import annotations

import argparse
import asyncio
import collections
import os
import pathlib
import sys

from .hass import HassClient
from .hass import slugify_all
from .mapping import build_rows
from .mapping import load_yaml_sources
from .mapping import write_csv
from .snapshot import Snapshot
from .snapshot import fetch_snapshot

HOMEASSISTANT_FILES = (
    pathlib.Path(__file__).resolve().parents[2] / "roles" / "homeassistant" / "files"
)


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
    rows = build_rows(
        Snapshot.load(args.snapshot), load_yaml_sources(args.files), hass_slugify
    )
    write_csv(rows, args.out)
    counts = collections.Counter(row.status for row in rows)
    summary = ", ".join(f"{counts[status]} {status}" for status in sorted(counts))
    print(f"{args.out}: {len(rows)} rows ({summary})")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m tools.homeassistant_rename")
    subparsers = parser.add_subparsers(dest="command", required=True)

    mapping = subparsers.add_parser(
        "map", help="write the old-to-new naming mapping to a CSV file"
    )
    mapping.add_argument("--files", default=HOMEASSISTANT_FILES, type=pathlib.Path)
    mapping.add_argument("--out", required=True, type=pathlib.Path)
    mapping.add_argument("--snapshot", required=True, type=pathlib.Path)
    mapping.set_defaults(handler=run_map)

    snapshot = subparsers.add_parser(
        "snapshot", help="save the registries and states to a JSON file"
    )
    snapshot.add_argument("--out", required=True, type=pathlib.Path)
    snapshot.set_defaults(handler=run_snapshot)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = args.handler(args)
    if asyncio.iscoroutine(result):
        asyncio.run(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
