import json
from typing import Any, AsyncIterator

from starlette.testclient import TestClient

from hotaru.server.server import Server


def _decode_sse(response: Any) -> list[dict[str, Any]]:
    rows = [row for row in response.iter_lines() if row]
    events: list[dict[str, Any]] = []
    for row in rows:
        payload = str(row).removeprefix("data: ").strip()
        if not payload:
            continue
        events.append(json.loads(payload))
    return events


def test_v1_event_stream_filters_by_session_id(monkeypatch, app_ctx) -> None:  # type: ignore[no-untyped-def]
    async def fake_events(cls, bus) -> AsyncIterator[dict[str, Any]]:  # type: ignore[no-untyped-def]
        yield {"type": "message.updated", "session_id": "session_1", "data": {"info": {"session_id": "session_1", "id": "m_1"}}}
        yield {"type": "message.updated", "session_id": "session_2", "data": {"info": {"session_id": "session_2", "id": "m_2"}}}

    monkeypatch.setattr("hotaru.app_services.event_service.EventService.stream", classmethod(fake_events))

    app = Server._create_app(app_ctx)
    with TestClient(app) as client:
        with client.stream("GET", "/v1/events", params={"session_id": "session_1"}) as response:
            assert response.status_code == 200
            events = _decode_sse(response)

    assert len(events) == 1
    assert events[0]["type"] == "message.updated"
    assert events[0]["data"]["info"]["id"] == "m_1"


def test_v1_event_stream_without_session_filter_returns_all(monkeypatch, app_ctx) -> None:  # type: ignore[no-untyped-def]
    async def fake_events(cls, bus) -> AsyncIterator[dict[str, Any]]:  # type: ignore[no-untyped-def]
        yield {"type": "session.status", "session_id": "session_1", "data": {"session_id": "session_1", "status": {"type": "working"}}}
        yield {"type": "session.status", "session_id": "session_2", "data": {"session_id": "session_2", "status": {"type": "idle"}}}

    monkeypatch.setattr("hotaru.app_services.event_service.EventService.stream", classmethod(fake_events))

    app = Server._create_app(app_ctx)
    with TestClient(app) as client:
        with client.stream("GET", "/v1/events") as response:
            assert response.status_code == 200
            events = _decode_sse(response)

    assert len(events) == 2
    assert {item["data"]["session_id"] for item in events} == {"session_1", "session_2"}
