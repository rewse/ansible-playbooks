"""Minimal Home Assistant WebSocket API client."""

from __future__ import annotations

import json
from typing import Any


class HassError(Exception):
    """Raised when Home Assistant rejects authentication or a command."""


def websocket_url(url: str) -> str:
    """Returns the WebSocket API endpoint for a Home Assistant base URL."""
    base = url.rstrip("/")
    if base.startswith("https://"):
        base = "wss://" + base.removeprefix("https://")
    elif base.startswith("http://"):
        base = "ws://" + base.removeprefix("http://")
    return base + "/api/websocket"


class HassClient:
    """Sends commands over one authenticated WebSocket connection."""

    def __init__(self, websocket: Any) -> None:
        self._websocket = websocket
        self._next_id = 1

    @classmethod
    async def connect(cls, url: str, token: str) -> HassClient:
        # websockets is imported here so that modules importing this one,
        # including the tests, do not need it installed.
        import websockets

        websocket = await websockets.connect(websocket_url(url), max_size=None)
        try:
            message = json.loads(await websocket.recv())
            if message.get("type") != "auth_required":
                raise HassError(f"unexpected greeting: {message.get('type')}")
            await websocket.send(json.dumps({"type": "auth", "access_token": token}))
            message = json.loads(await websocket.recv())
            if message.get("type") != "auth_ok":
                raise HassError(f"authentication failed: {message.get('message')}")
        except BaseException:
            await websocket.close()
            raise
        return cls(websocket)

    async def _send(self, type_: str, payload: dict[str, Any]) -> int:
        message_id = self._next_id
        self._next_id += 1
        await self._websocket.send(
            json.dumps({"id": message_id, "type": type_, **payload})
        )
        return message_id

    async def _receive(self, message_id: int, type_: str) -> dict[str, Any]:
        while True:
            message = json.loads(await self._websocket.recv())
            if message.get("id") == message_id and message.get("type") == type_:
                return message

    async def _result(self, message_id: int, type_: str) -> Any:
        message = await self._receive(message_id, "result")
        if not message.get("success"):
            error = message.get("error") or {}
            raise HassError(
                f"{type_} failed: {error.get('code')}: {error.get('message')}"
            )
        return message.get("result")

    async def call(self, type_: str, **payload: Any) -> Any:
        """Sends a command and returns its result."""
        message_id = await self._send(type_, payload)
        return await self._result(message_id, type_)

    async def render(
        self, template: str, variables: dict[str, Any] | None = None
    ) -> str:
        """Renders a template and returns its first result."""
        payload: dict[str, Any] = {"template": template}
        if variables is not None:
            payload["variables"] = variables
        message_id = await self._send("render_template", payload)
        await self._result(message_id, "render_template")
        event = (await self._receive(message_id, "event"))["event"]
        await self.call("unsubscribe_events", subscription=message_id)
        if "error" in event:
            raise HassError(f"render_template failed: {event['error']}")
        result = event["result"]
        # Home Assistant parses rendered output that looks like a literal into
        # a native value, so a JSON list arrives as a list. Return JSON text in
        # that case so callers always receive a string.
        return result if isinstance(result, str) else json.dumps(result)

    async def close(self) -> None:
        await self._websocket.close()


async def slugify_all(client: HassClient, names: list[str]) -> dict[str, str]:
    """Slugifies names with Home Assistant's own filter in one render."""
    rendered = await client.render(
        "{{ names | map('slugify') | list | tojson }}", {"names": names}
    )
    return dict(zip(names, json.loads(rendered), strict=True))
