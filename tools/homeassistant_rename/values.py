"""Carries helper values across the rename of their YAML keys.

Home Assistant restores a helper's value by its entity ID, so a helper whose
key changes starts from its initial value. capture() records the states before
the rename under the new IDs, and restore() sets them again afterwards.
"""

from __future__ import annotations

from typing import Any

from .mapping import Row
from .registry import Client
from .snapshot import Snapshot

MISSING_STATES = frozenset({"unavailable", "unknown"})


def capture(snapshot: Snapshot, rows: list[Row]) -> dict[str, dict[str, Any]]:
    """Maps the new ID of each renamed YAML key to its current state."""
    return {
        row.new_id: snapshot.states[row.old_id]
        for row in rows
        if row.kind == "entity"
        and row.status == "auto"
        and row.source == "yaml_key"
        and row.old_id != row.new_id
        and row.old_id in snapshot.states
    }


def _datetime_data(state: dict[str, Any]) -> dict[str, Any]:
    attributes = state.get("attributes", {})
    has_date = attributes.get("has_date", False)
    has_time = attributes.get("has_time", False)
    if has_date and has_time:
        return {"datetime": state["state"]}
    if has_date:
        return {"date": state["state"]}
    return {"time": state["state"]}


def _call(entity_id: str, state: dict[str, Any]) -> tuple[str, str, dict] | None:
    domain = entity_id.split(".", 1)[0]
    value = state["state"]
    data: dict[str, Any] = {"entity_id": entity_id}
    if domain == "input_boolean":
        return (domain, "turn_on" if value == "on" else "turn_off", data)
    if domain == "input_datetime":
        return (domain, "set_datetime", data | _datetime_data(state))
    if domain == "input_number":
        return (domain, "set_value", data | {"value": float(value)})
    if domain == "input_select":
        return (domain, "select_option", data | {"option": value})
    return None


def restore_calls(
    captured: dict[str, dict[str, Any]],
) -> list[tuple[str, str, dict[str, Any]]]:
    """Lists the (domain, service, data) calls that set the captured values.

    Domains without a value, such as script, and states that carry no value
    produce no call.
    """
    calls = []
    for entity_id in sorted(captured):
        state = captured[entity_id]
        if state["state"] in MISSING_STATES:
            continue
        call = _call(entity_id, state)
        if call is not None:
            calls.append(call)
    return calls


async def restore(client: Client, captured: dict[str, dict[str, Any]]) -> None:
    """Sets the captured values through Home Assistant actions."""
    for domain, service, data in restore_calls(captured):
        await client.call(
            "call_service", domain=domain, service=service, service_data=data
        )
