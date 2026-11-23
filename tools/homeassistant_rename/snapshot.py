"""Snapshot of the Home Assistant registries and states."""

from __future__ import annotations

import dataclasses
import json
import pathlib
from typing import Any

from .hass import HassClient


@dataclasses.dataclass
class Snapshot:
    """Areas, devices, entities, and states read at one point in time."""

    areas: list[dict[str, Any]]
    devices: list[dict[str, Any]]
    entities: list[dict[str, Any]]
    states: dict[str, dict[str, Any]]

    @classmethod
    def from_lists(
        cls,
        areas: list[dict[str, Any]],
        devices: list[dict[str, Any]],
        entities: list[dict[str, Any]],
        states: list[dict[str, Any]],
    ) -> Snapshot:
        """Builds a snapshot from API lists, keying states by entity ID."""
        return cls(
            areas=areas,
            devices=devices,
            entities=entities,
            states={state["entity_id"]: state for state in states},
        )

    def save(self, path: str | pathlib.Path) -> None:
        pathlib.Path(path).write_text(
            json.dumps(dataclasses.asdict(self), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str | pathlib.Path) -> Snapshot:
        return cls(**json.loads(pathlib.Path(path).read_text(encoding="utf-8")))


async def fetch_snapshot(client: HassClient) -> Snapshot:
    """Reads the area, device, and entity registries and all states."""
    return Snapshot.from_lists(
        areas=await client.call("config/area_registry/list"),
        devices=await client.call("config/device_registry/list"),
        entities=await client.call("config/entity_registry/list"),
        states=await client.call("get_states"),
    )
