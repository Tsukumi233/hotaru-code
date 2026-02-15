from pathlib import Path

import pytest

from hotaru.core.global_paths import GlobalPath
from hotaru.core.id import Identifier
from hotaru.session import Session
from hotaru.session.message_store import (
    MessageInfo,
    MessageTime,
    ModelRef,
    ReasoningPart,
    StepFinishPart,
    StepStartPart,
    TextPart,
    TokenUsage,
    ToolPart,
    ToolState,
    ToolStateTime,
)
from hotaru.storage import Storage
from hotaru.tui.context.sync import SyncContext


def test_set_sessions_sorts_by_updated_descending() -> None:
    ctx = SyncContext()
    ctx.set_sessions(
        [
            {"id": "s1", "time": {"updated": 10}},
            {"id": "s2", "time": {"updated": 100}},
            {"id": "s3", "time": {"updated": 50}},
        ]
    )

    assert [item["id"] for item in ctx.data.sessions] == ["s2", "s3", "s1"]


def test_update_session_keeps_recency_order() -> None:
    ctx = SyncContext()
    ctx.set_sessions(
        [
            {"id": "s1", "time": {"updated": 10}},
            {"id": "s2", "time": {"updated": 100}},
        ]
    )

    ctx.update_session({"id": "s1", "time": {"updated": 200}})
    assert [item["id"] for item in ctx.data.sessions] == ["s1", "s2"]


def _setup_storage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(GlobalPath, "data", classmethod(lambda cls: str(data_dir)))
    Storage.reset()


@pytest.mark.anyio
async def test_sync_session_prefers_structured_messages(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _setup_storage(monkeypatch, tmp_path)

    session = await Session.create(project_id="p1", agent="build", directory=str(tmp_path))
    user_id = Identifier.ascending("message")
    assistant_id = Identifier.ascending("message")

    await Session.update_message(
        MessageInfo(
            id=user_id,
            session_id=session.id,
            role="user",
            agent="build",
            model=ModelRef(provider_id="openai", model_id="gpt-5"),
            time=MessageTime(created=1, completed=1),
        )
    )
    await Session.update_part(
        TextPart(
            id=Identifier.ascending("part"),
            session_id=session.id,
            message_id=user_id,
            text="hello",
        )
    )

    await Session.update_message(
        MessageInfo(
            id=assistant_id,
            session_id=session.id,
            role="assistant",
            agent="build",
            model=ModelRef(provider_id="openai", model_id="gpt-5"),
            time=MessageTime(created=2, completed=6),
            tokens=TokenUsage(input=10, output=3, reasoning=2),
            cost=0.12,
            finish="stop",
        )
    )
    await Session.update_part(
        StepStartPart(
            id=Identifier.ascending("part"),
            session_id=session.id,
            message_id=assistant_id,
        )
    )
    await Session.update_part(
        ReasoningPart(
            id=Identifier.ascending("part"),
            session_id=session.id,
            message_id=assistant_id,
            text="thinking",
            time={"start": 2, "end": 3},
        )
    )
    await Session.update_part(
        ToolPart(
            id=Identifier.ascending("part"),
            session_id=session.id,
            message_id=assistant_id,
            tool="read",
            call_id="call_1",
            state=ToolState(
                status="completed",
                input={"filePath": "README.md"},
                output="ok",
                time=ToolStateTime(start=3, end=4),
            ),
        )
    )
    await Session.update_part(
        StepFinishPart(
            id=Identifier.ascending("part"),
            session_id=session.id,
            message_id=assistant_id,
            reason="stop",
            tokens=TokenUsage(input=10, output=3, reasoning=2),
        )
    )

    ctx = SyncContext()
    await ctx.sync_session(session.id, force=True)
    messages = ctx.get_messages(session.id)

    assert [msg["role"] for msg in messages] == ["user", "assistant"]
    assistant = messages[1]
    assert assistant["info"]["model"]["provider_id"] == "openai"
    assert assistant["metadata"]["usage"]["input_tokens"] == 10
    part_types = [part.get("type") for part in assistant.get("parts", [])]
    assert "reasoning" in part_types
    assert "tool" in part_types
    assert "step-start" in part_types
    assert "step-finish" in part_types
