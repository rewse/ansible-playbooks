"""Applies the naming mapping to the Home Assistant registries and reverts it."""

from __future__ import annotations

import dataclasses
import json
import os
import pathlib
from typing import Any, Literal, Protocol

from .mapping import Kind
from .mapping import Row
from .snapshot import Snapshot

COMMANDS: dict[Kind, str] = {
    "area": "config/area_registry/update",
    "device": "config/device_registry/update",
    "entity": "config/entity_registry/update",
}
TEMPORARY_SUFFIX = "_renaming"


class Client(Protocol):
    """The part of HassClient these functions use."""

    async def call(self, type_: str, **payload: Any) -> Any: ...


@dataclasses.dataclass
class Op:
    """One registry update and the update that undoes it."""

    kind: Literal["area", "device", "entity"]
    key: str
    payload: dict[str, Any]
    undo: dict[str, Any]


@dataclasses.dataclass
class _Move:
    old_id: str
    new_id: str
    # Extra fields sent with the move that reaches new_id, and their undo.
    extra: dict[str, Any]
    extra_undo: dict[str, Any]


def _area_ops(rows: list[Row]) -> list[Op]:
    return [
        Op(
            kind="area",
            key=row.key,
            payload={"area_id": row.key, "name": row.new_name},
            undo={"area_id": row.key, "name": row.old_name},
        )
        for row in rows
        if row.kind == "area" and row.old_name != row.new_name
    ]


def _device_ops(rows: list[Row], snapshot: Snapshot | None) -> list[Op]:
    devices = {device["id"]: device for device in snapshot.devices} if snapshot else {}
    ops = []
    for row in rows:
        if row.kind != "device" or row.old_name == row.new_name:
            continue
        # name_by_user is None when the device shows its integration's name, so
        # the undo restores None rather than pinning that name.
        previous = (
            devices[row.key].get("name_by_user") if row.key in devices else row.old_name
        )
        ops.append(
            Op(
                kind="device",
                key=row.key,
                payload={"device_id": row.key, "name_by_user": row.new_name},
                undo={"device_id": row.key, "name_by_user": previous},
            )
        )
    return ops


def _entity_extras(
    row: Row, entity: dict[str, Any] | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Returns the name and area fields an entity's update carries."""
    extra: dict[str, Any] = {}
    extra_undo: dict[str, Any] = {}
    # A YAML entity takes its name from YAML; a registry name would override it.
    if row.source == "registry" and row.new_name != row.old_name:
        extra["name"] = row.new_name
        extra_undo["name"] = entity.get("name") if entity else row.old_name
    if (
        entity is not None
        and entity.get("device_id") is None
        and row.room
        and entity.get("area_id") != row.room
    ):
        extra["area_id"] = row.room
        extra_undo["area_id"] = entity.get("area_id")
    return extra, extra_undo


def _temporary_id(entity_id: str, occupied: set[str]) -> str:
    candidate = entity_id + TEMPORARY_SUFFIX
    number = 2
    while candidate in occupied:
        candidate = f"{entity_id}{TEMPORARY_SUFFIX}_{number}"
        number += 1
    return candidate


def _move_op(old_id: str, new_id: str, move: _Move | None = None) -> Op:
    payload: dict[str, Any] = {"entity_id": old_id, "new_entity_id": new_id}
    undo: dict[str, Any] = {"entity_id": new_id, "new_entity_id": old_id}
    if move is not None:
        payload.update(move.extra)
        undo.update(move.extra_undo)
    return Op(kind="entity", key=old_id, payload=payload, undo=undo)


def _order_moves(moves: list[_Move], existing_ids: set[str]) -> list[Op]:
    """Orders moves so each target is vacated before it is taken.

    A cycle is broken by moving one of its entities to a temporary ID in the
    same domain first.
    """
    targets: dict[str, str] = {}
    for move in moves:
        if move.new_id in targets:
            raise ValueError(
                f"{move.old_id} and {targets[move.new_id]} both move to {move.new_id}"
            )
        targets[move.new_id] = move.old_id
    pending = {move.old_id: move for move in moves}
    for move in moves:
        if move.new_id in existing_ids and move.new_id not in pending:
            raise ValueError(
                f"{move.new_id} is already used; {move.old_id} cannot move"
            )

    occupied = set(existing_ids) | set(pending)
    # Maps the ID an entity currently has to the move it still needs.
    current = dict(pending)
    ops: list[Op] = []
    while current:
        ready = next(
            (old_id for old_id, move in current.items() if move.new_id not in occupied),
            None,
        )
        if ready is not None:
            move = current.pop(ready)
            ops.append(_move_op(ready, move.new_id, move))
            occupied.discard(ready)
            occupied.add(move.new_id)
            continue
        # Every target is held by another pending entity, so following the
        # targets from any entity reaches a cycle.
        seen: set[str] = set()
        node = next(iter(current))
        while node not in seen:
            seen.add(node)
            node = current[node].new_id
        temporary = _temporary_id(node, occupied)
        ops.append(_move_op(node, temporary))
        current[temporary] = current.pop(node)
        occupied.discard(node)
        occupied.add(temporary)
    return ops


def plan_ops(
    rows: list[Row], existing_ids: set[str], snapshot: Snapshot | None = None
) -> list[Op]:
    """Plans the registry updates for the auto rows: areas, devices, entities.

    existing_ids holds every entity ID in use, registered or only in states.
    The snapshot supplies the values undo restores and which entities have no
    device; without it, undo restores the mapping's old names and no entity
    gets an area.
    """
    rows = [row for row in rows if row.status == "auto"]
    entities = (
        {entity["entity_id"]: entity for entity in snapshot.entities}
        if snapshot
        else {}
    )
    renames: list[Op] = []
    moves: list[_Move] = []
    for row in rows:
        if row.kind != "entity" or row.source == "yaml_key":
            continue
        extra, extra_undo = _entity_extras(row, entities.get(row.old_id))
        if row.old_id != row.new_id:
            moves.append(_Move(row.old_id, row.new_id, extra, extra_undo))
        elif extra:
            renames.append(
                Op(
                    kind="entity",
                    key=row.old_id,
                    payload={"entity_id": row.old_id, **extra},
                    undo={"entity_id": row.old_id, **extra_undo},
                )
            )
    return (
        _area_ops(rows)
        + _device_ops(rows, snapshot)
        + renames
        + _order_moves(moves, existing_ids)
    )


def describe(op: Op) -> str:
    fields = ", ".join(f"{key}={value!r}" for key, value in op.payload.items())
    return f"{COMMANDS[op.kind]}: {fields}"


async def apply_ops(
    client: Client, ops: list[Op], journal: pathlib.Path, dry_run: bool
) -> None:
    """Applies ops in order, appending each one to the journal once it succeeds.

    A dry run prints the ops and neither calls Home Assistant nor writes the
    journal.
    """
    if dry_run:
        for op in ops:
            print(describe(op))
        return
    journal.parent.mkdir(parents=True, exist_ok=True)
    with journal.open("a", encoding="utf-8") as file:
        for op in ops:
            await client.call(COMMANDS[op.kind], **op.payload)
            record = {"type": COMMANDS[op.kind], **dataclasses.asdict(op)}
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
            file.flush()


def _rewrite_journal(journal: pathlib.Path, lines: list[str]) -> None:
    """Replaces the journal with lines, so a crash leaves the old or new file."""
    staging = journal.with_name(journal.name + ".tmp")
    with staging.open("w", encoding="utf-8") as file:
        file.writelines(line + "\n" for line in lines)
        file.flush()
        os.fsync(file.fileno())
    staging.replace(journal)


async def revert(client: Client, journal: pathlib.Path) -> None:
    """Applies the undo of every journal entry, newest first.

    Each undone entry is dropped from the journal as soon as it succeeds, so a
    revert that stops partway resumes where it stopped. The emptied journal is
    renamed to <name>.reverted, which frees its path for the next apply.
    """
    lines = [
        line
        for line in journal.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    while lines:
        record = json.loads(lines[-1])
        await client.call(record["type"], **record["undo"])
        lines.pop()
        _rewrite_journal(journal, lines)
    journal.replace(journal.with_name(journal.name + ".reverted"))


def _yaml_key_renames(rows: list[Row]) -> list[Row]:
    return [
        row
        for row in rows
        if row.kind == "entity"
        and row.source == "yaml_key"
        and row.status == "auto"
        and row.old_id != row.new_id
    ]


async def remove_orphans(client: Client, rows: list[Row]) -> list[str]:
    """Removes registry entries left behind by renamed YAML keys.

    An old ID is removed only when it is registered and has no state, which
    means the deployed YAML no longer defines it.
    """
    registered = {
        entity["entity_id"]
        for entity in await client.call("config/entity_registry/list")
    }
    states = {state["entity_id"] for state in await client.call("get_states")}
    removed = []
    for row in _yaml_key_renames(rows):
        if row.old_id in registered and row.old_id not in states:
            await client.call("config/entity_registry/remove", entity_id=row.old_id)
            removed.append(row.old_id)
    return removed


async def assign_areas(client: Client, rows: list[Row]) -> None:
    """Assigns each renamed YAML key entity to its room once it is registered."""
    registered = {
        entity["entity_id"]: entity
        for entity in await client.call("config/entity_registry/list")
    }
    for row in _yaml_key_renames(rows):
        entity = registered.get(row.new_id)
        if entity is None or not row.room or entity.get("area_id") == row.room:
            continue
        await client.call(
            "config/entity_registry/update", entity_id=row.new_id, area_id=row.room
        )
