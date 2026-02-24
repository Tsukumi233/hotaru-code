"""Event streaming application service."""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

from ..core.bus import Bus


def _extract_session_id(data: dict[str, Any]) -> str:
    """Extract session_id from event data at any nesting level."""
    direct = data.get("session_id")
    if isinstance(direct, str) and direct:
        return direct

    info = data.get("info")
    if isinstance(info, dict):
        scoped = info.get("session_id")
        if isinstance(scoped, str) and scoped:
            return scoped

    part = data.get("part")
    if isinstance(part, dict):
        scoped = part.get("session_id")
        if isinstance(scoped, str) and scoped:
            return scoped

    session = data.get("session")
    if isinstance(session, dict):
        scoped = session.get("id")
        if isinstance(scoped, str) and scoped:
            return scoped

    return ""


class EventService:
    """Thin orchestration for bus event streaming."""

    @classmethod
    async def stream(cls, bus: Bus) -> AsyncIterator[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        def on_event(event: Any) -> None:
            if isinstance(event, dict):
                event_type = str(event.get("type", "server.event"))
                data = event.get("properties", event.get("data", {}))
                if not isinstance(data, dict):
                    data = {"value": data}
            elif hasattr(event, "type") and hasattr(event, "properties"):
                event_type = str(event.type)
                data = event.properties if isinstance(event.properties, dict) else {}
            elif hasattr(event, "model_dump"):
                payload = event.model_dump()
                event_type = str(payload.get("type", "server.event"))
                data = payload.get("properties", {})
                if not isinstance(data, dict):
                    data = {"value": data}
            else:
                event_type = "server.event"
                data = {}

            envelope: dict[str, Any] = {"type": event_type, "data": data}
            session_id = _extract_session_id(data)
            if session_id:
                envelope["session_id"] = session_id
            queue.put_nowait(envelope)

        unsubscribe = bus._raw_subscribe("*", on_event)

        try:
            yield {"type": "server.connected", "data": {}}
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield event
                except asyncio.TimeoutError:
                    yield {"type": "server.heartbeat", "data": {}}
        except asyncio.CancelledError:
            return
        finally:
            unsubscribe()
