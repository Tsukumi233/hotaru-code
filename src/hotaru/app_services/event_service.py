"""Event streaming application service."""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

from ..core.bus import Bus


class EventService:
    """Thin orchestration for bus event streaming."""

    @classmethod
    async def stream(cls) -> AsyncIterator[dict[str, Any]]:
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

            queue.put_nowait({"type": event_type, "data": data})

        unsubscribe = Bus.subscribe_all(on_event)

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
