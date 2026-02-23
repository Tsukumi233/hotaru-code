"""Event stream transport routes."""

from __future__ import annotations

import json
import time
from typing import AsyncIterator

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from ...app_services import EventService
from ...runtime import AppContext
from ..deps import resolve_app_context
from ..schemas import SseEnvelope

router = APIRouter(prefix="/v1/events", tags=["events"])


def _event_session_id(event: dict[str, object]) -> str:
    session_id = event.get("session_id")
    if isinstance(session_id, str) and session_id:
        return session_id

    data = event.get("data")
    if not isinstance(data, dict):
        return ""

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
    return ""


def _matches_session_filter(event: dict[str, object], session_id: str) -> bool:
    if not session_id:
        return True

    event_type = str(event.get("type") or "")
    if event_type in {"server.connected", "server.heartbeat"}:
        return True
    if event_type.startswith("pty."):
        return True
    return _event_session_id(event) == session_id


def _sse_data(event: dict[str, object], *, session_id: str | None = None) -> str:
    event_type = str(event.get("type", "server.event"))
    data = event.get("data", {})
    if not isinstance(data, dict):
        data = {"value": data}
    envelope: dict[str, object] = {
        "type": event_type,
        "data": data,
        "timestamp": int(time.time() * 1000),
    }
    if session_id:
        envelope["session_id"] = session_id
    return f"data: {json.dumps(envelope)}\n\n"


def _sse_response(iterator: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(
        iterator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("", response_model=SseEnvelope)
async def stream_events(
    ctx: AppContext = Depends(resolve_app_context),
    session_id: str = Query(default=""),
) -> StreamingResponse:
    stream = EventService.stream(ctx.bus)

    async def event_generator() -> AsyncIterator[str]:
        try:
            async for event in stream:
                if not _matches_session_filter(event, session_id):
                    continue
                event_session_id = _event_session_id(event)
                yield _sse_data(event, session_id=event_session_id if event_session_id else None)
        except Exception as exc:
            yield _sse_data({"type": "error", "data": {"error": str(exc)}})

    return _sse_response(event_generator())
