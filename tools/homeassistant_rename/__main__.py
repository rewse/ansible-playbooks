"""Command line entry point: python -m tools.homeassistant_rename."""

from __future__ import annotations

import argparse
import asyncio
import os
import pathlib
import sys

from .hass import HassClient
from .snapshot import fetch_snapshot


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m tools.homeassistant_rename")
    subparsers = parser.add_subparsers(dest="command", required=True)

    snapshot = subparsers.add_parser(
        "snapshot", help="save the registries and states to a JSON file"
    )
    snapshot.add_argument("--out", required=True, type=pathlib.Path)
    snapshot.set_defaults(handler=run_snapshot)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    asyncio.run(args.handler(args))
    return 0


if __name__ == "__main__":
    sys.exit(main())
