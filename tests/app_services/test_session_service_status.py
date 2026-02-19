import asyncio
from pathlib import Path

import pytest

from hotaru.app_services.session_service import SessionService
from hotaru.core.bus import Bus
from hotaru.core.global_paths import GlobalPath
from hotaru.session import Session
from hotaru.session.processor import ProcessorResult
from hotaru.session.prompting import PromptResult
from hotaru.storage import Storage


def _setup_storage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(GlobalPath, "data", classmethod(lambda cls: str(data_dir)))
    Storage.reset()
    Bus.reset()
    SessionService.reset_runtime()


@pytest.mark.anyio
async def test_message_publishes_working_then_idle(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _setup_storage(monkeypatch, tmp_path)
    session = await Session.create(
        project_id="p1",
        agent="build",
        directory=str(tmp_path),
        provider_id="openai",
        model_id="gpt-5",
    )

    async def fake_prompt(cls, **_kwargs):
        return PromptResult(
            result=ProcessorResult(status="stop", text="ok"),
            assistant_message_id="message_2",
            user_message_id="message_1",
            text="ok",
        )

    monkeypatch.setattr("hotaru.app_services.session_service.SessionPrompt.prompt", classmethod(fake_prompt))

    events: list[dict] = []
    unsubscribe = Bus.subscribe_all(lambda payload: events.append({"type": payload.type, "properties": payload.properties}))
    try:
        result = await SessionService.message(
            session.id,
            {"content": "hello", "agent": "build", "model": "openai/gpt-5"},
            str(tmp_path),
        )
    finally:
        unsubscribe()

    statuses = [
        event["properties"]["status"]["type"]
        for event in events
        if event["type"] == "session.status" and event["properties"]["session_id"] == session.id
    ]
    assert statuses == ["working", "idle"]
    assert result["ok"] is True
    assert result["assistant_message_id"] == "message_2"


@pytest.mark.anyio
async def test_message_publishes_idle_even_when_prompt_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _setup_storage(monkeypatch, tmp_path)
    session = await Session.create(
        project_id="p1",
        agent="build",
        directory=str(tmp_path),
        provider_id="openai",
        model_id="gpt-5",
    )

    async def fake_prompt(cls, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("hotaru.app_services.session_service.SessionPrompt.prompt", classmethod(fake_prompt))

    events: list[dict] = []
    unsubscribe = Bus.subscribe_all(lambda payload: events.append({"type": payload.type, "properties": payload.properties}))
    try:
        with pytest.raises(RuntimeError, match="boom"):
            await SessionService.message(
                session.id,
                {"content": "hello", "agent": "build", "model": "openai/gpt-5"},
                str(tmp_path),
            )
    finally:
        unsubscribe()

    statuses = [
        event["properties"]["status"]["type"]
        for event in events
        if event["type"] == "session.status" and event["properties"]["session_id"] == session.id
    ]
    assert statuses == ["working", "idle"]


@pytest.mark.anyio
async def test_interrupt_cancels_running_message_and_returns_interrupted_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _setup_storage(monkeypatch, tmp_path)
    session = await Session.create(
        project_id="p1",
        agent="build",
        directory=str(tmp_path),
        provider_id="openai",
        model_id="gpt-5",
    )

    started = asyncio.Event()

    async def fake_prompt(cls, **_kwargs):
        started.set()
        await asyncio.sleep(30)
        return PromptResult(
            result=ProcessorResult(status="stop", text="ok"),
            assistant_message_id="message_2",
            user_message_id="message_1",
            text="ok",
        )

    monkeypatch.setattr("hotaru.app_services.session_service.SessionPrompt.prompt", classmethod(fake_prompt))

    events: list[dict] = []
    unsubscribe = Bus.subscribe_all(
        lambda payload: events.append({"type": payload.type, "properties": payload.properties}),
    )
    try:
        msg_task = asyncio.create_task(
            SessionService.message(
                session.id,
                {"content": "hello", "agent": "build", "model": "openai/gpt-5"},
                str(tmp_path),
            )
        )
        await asyncio.wait_for(started.wait(), timeout=1.0)
        interrupted = await SessionService.interrupt(session.id)
        result = await msg_task
    finally:
        unsubscribe()

    statuses = [
        event["properties"]["status"]["type"]
        for event in events
        if event["type"] == "session.status" and event["properties"]["session_id"] == session.id
    ]
    assert interrupted == {"ok": True, "interrupted": True}
    assert statuses == ["working", "idle"]
    assert result["ok"] is False
    assert result["status"] == "interrupted"


@pytest.mark.anyio
async def test_interrupt_returns_false_when_session_is_idle(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _setup_storage(monkeypatch, tmp_path)
    session = await Session.create(
        project_id="p1",
        agent="build",
        directory=str(tmp_path),
        provider_id="openai",
        model_id="gpt-5",
    )
    result = await SessionService.interrupt(session.id)
    assert result == {"ok": True, "interrupted": False}
