from pathlib import Path

import pytest

from hotaru.core.bus import Bus
from hotaru.core.global_paths import GlobalPath
from hotaru.session import Session
from hotaru.session.message_store import MessageInfo, MessageTime, TextPart
from hotaru.storage import Storage


def _setup_storage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(GlobalPath, "data", classmethod(lambda cls: str(data_dir)))
    Storage.reset()
    Bus.reset()


@pytest.mark.anyio
async def test_update_message_publishes_message_updated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _setup_storage(monkeypatch, tmp_path)
    events: list[dict] = []
    unsubscribe = Bus.subscribe_all(lambda payload: events.append({"type": payload.type, "properties": payload.properties}))
    try:
        session = await Session.create(project_id="p1", agent="build", directory=str(tmp_path))
        await Session.update_message(
            MessageInfo(
                id="message_1",
                session_id=session.id,
                role="user",
                time=MessageTime(created=1),
            )
        )
    finally:
        unsubscribe()

    updated = [event for event in events if event["type"] == "message.updated"]
    assert len(updated) == 1
    assert updated[0]["properties"]["info"]["id"] == "message_1"
    assert updated[0]["properties"]["info"]["session_id"] == session.id


@pytest.mark.anyio
async def test_update_part_publishes_message_part_updated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _setup_storage(monkeypatch, tmp_path)
    events: list[dict] = []
    unsubscribe = Bus.subscribe_all(lambda payload: events.append({"type": payload.type, "properties": payload.properties}))
    try:
        session = await Session.create(project_id="p1", agent="build", directory=str(tmp_path))
        await Session.update_part(
            TextPart(
                id="part_1",
                session_id=session.id,
                message_id="message_1",
                text="hello",
            )
        )
    finally:
        unsubscribe()

    updated = [event for event in events if event["type"] == "message.part.updated"]
    assert len(updated) == 1
    assert updated[0]["properties"]["part"]["id"] == "part_1"
    assert updated[0]["properties"]["part"]["text"] == "hello"


@pytest.mark.anyio
async def test_update_part_delta_publishes_delta_and_updated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _setup_storage(monkeypatch, tmp_path)
    events: list[dict] = []
    unsubscribe = Bus.subscribe_all(lambda payload: events.append({"type": payload.type, "properties": payload.properties}))
    try:
        session = await Session.create(project_id="p1", agent="build", directory=str(tmp_path))
        await Session.update_part(
            TextPart(
                id="part_1",
                session_id=session.id,
                message_id="message_1",
                text="he",
            )
        )
        events.clear()
        await Session.update_part_delta(
            session_id=session.id,
            message_id="message_1",
            part_id="part_1",
            field="text",
            delta="llo",
        )
    finally:
        unsubscribe()

    delta = [event for event in events if event["type"] == "message.part.delta"]
    updated = [event for event in events if event["type"] == "message.part.updated"]
    assert len(delta) == 1
    assert delta[0]["properties"]["delta"] == "llo"
    assert len(updated) == 1
    assert updated[0]["properties"]["part"]["text"] == "hello"
