from pathlib import Path

import pytest

from hotaru.core.global_paths import GlobalPath
from hotaru.core.id import Identifier
from hotaru.session.message_store import (
    CompactionPart,
    MessageInfo,
    MessageTime,
    TextPart,
    ToolPart,
    ToolState,
    ToolStateTime,
    WithParts,
    filter_compacted,
    to_model_messages,
)
from hotaru.session.session import Session
from hotaru.storage import Storage


def _setup_storage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(GlobalPath, "data", classmethod(lambda cls: str(data_dir)))
    Storage.reset()


@pytest.mark.anyio
async def test_message_store_roundtrip_and_delta(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _setup_storage(monkeypatch, tmp_path)

    session = await Session.create(project_id="p1", agent="build", directory=str(tmp_path))

    msg = MessageInfo(
        id=Identifier.ascending("message"),
        session_id=session.id,
        role="assistant",
        agent="build",
        time=MessageTime(created=1, completed=2),
    )
    await Session.update_message(msg)

    text = TextPart(
        id=Identifier.ascending("part"),
        session_id=session.id,
        message_id=msg.id,
        text="hello",
    )
    await Session.update_part(text)

    tool = ToolPart(
        id=Identifier.ascending("part"),
        session_id=session.id,
        message_id=msg.id,
        tool="read",
        call_id="call_1",
        state=ToolState(
            status="completed",
            input={"filePath": "README.md"},
            output="ok",
            time=ToolStateTime(start=1, end=2),
        ),
    )
    await Session.update_part(tool)

    updated = await Session.update_part_delta(
        session_id=session.id,
        message_id=msg.id,
        part_id=text.id,
        field="text",
        delta=" world",
    )
    assert updated is not None

    msgs = await Session.messages(session_id=session.id)
    assert len(msgs) == 1
    assert msgs[0].info.id == msg.id
    assert len(msgs[0].parts) == 2
    text_part = [p for p in msgs[0].parts if getattr(p, "type", "") == "text"][0]
    assert text_part.text == "hello world"


@pytest.mark.anyio
async def test_delete_messages_removes_message_store_parts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _setup_storage(monkeypatch, tmp_path)

    session = await Session.create(project_id="p1", agent="build", directory=str(tmp_path))
    msg = MessageInfo(
        id=Identifier.ascending("message"),
        session_id=session.id,
        role="assistant",
        agent="build",
        time=MessageTime(created=1, completed=2),
    )
    await Session.update_message(msg)
    await Session.update_part(
        TextPart(
            id=Identifier.ascending("part"),
            session_id=session.id,
            message_id=msg.id,
            text="payload",
        )
    )

    deleted = await Session.delete_messages(session.id, [msg.id])
    assert deleted == 1
    assert await Session.messages(session_id=session.id) == []


def test_filter_compacted_keeps_latest_compaction_window() -> None:
    c1 = "message_compaction"
    messages = [
        WithParts(
            info=MessageInfo(id="message_old_user", session_id="s1", role="user", time=MessageTime(created=1)),
            parts=[TextPart(id="part_1", session_id="s1", message_id="message_old_user", text="old")],
        ),
        WithParts(
            info=MessageInfo(
                id="message_old_assistant",
                session_id="s1",
                role="assistant",
                parent_id="message_old_user",
                time=MessageTime(created=2),
                finish="stop",
            ),
            parts=[TextPart(id="part_2", session_id="s1", message_id="message_old_assistant", text="done")],
        ),
        WithParts(
            info=MessageInfo(id=c1, session_id="s1", role="user", time=MessageTime(created=3)),
            parts=[CompactionPart(id="part_3", session_id="s1", message_id=c1, auto=True)],
        ),
        WithParts(
            info=MessageInfo(
                id="message_summary",
                session_id="s1",
                role="assistant",
                parent_id=c1,
                summary=True,
                finish="stop",
                time=MessageTime(created=4),
            ),
            parts=[TextPart(id="part_4", session_id="s1", message_id="message_summary", text="summary")],
        ),
        WithParts(
            info=MessageInfo(id="message_next_user", session_id="s1", role="user", time=MessageTime(created=5)),
            parts=[TextPart(id="part_5", session_id="s1", message_id="message_next_user", text="continue")],
        ),
    ]

    filtered = filter_compacted(messages)
    assert [m.info.id for m in filtered] == [c1, "message_summary", "message_next_user"]


def test_to_model_messages_includes_interrupted_tool_results() -> None:
    messages = [
        WithParts(
            info=MessageInfo(id="m1", session_id="s1", role="user", time=MessageTime(created=1)),
            parts=[TextPart(id="p1", session_id="s1", message_id="m1", text="run tool")],
        ),
        WithParts(
            info=MessageInfo(id="m2", session_id="s1", role="assistant", time=MessageTime(created=2)),
            parts=[
                ToolPart(
                    id="p2",
                    session_id="s1",
                    message_id="m2",
                    tool="read",
                    call_id="call_1",
                    state=ToolState(
                        status="running",
                        input={"filePath": "README.md"},
                        time=ToolStateTime(start=2),
                    ),
                )
            ],
        ),
    ]

    model_messages = to_model_messages(messages)
    assert model_messages[1]["role"] == "assistant"
    assert model_messages[1]["tool_calls"][0]["id"] == "call_1"
    assert model_messages[2]["role"] == "tool"
    assert model_messages[2]["content"] == "[Tool execution was interrupted]"
