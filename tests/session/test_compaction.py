from types import SimpleNamespace

import pytest

from hotaru.core.config import ConfigManager
from hotaru.provider.models import ModelLimit
from hotaru.provider.provider import ProcessedModelInfo
from hotaru.session.compaction import SessionCompaction
from hotaru.session.message_store import (
    MessageInfo,
    MessageTime,
    TextPart,
    TokenUsage,
    ToolPart,
    ToolState,
    ToolStateTime,
    WithParts,
)
from hotaru.session.session import Session


@pytest.mark.anyio
async def test_is_overflow_respects_reserved_compaction_buffer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_config(cls):
        return SimpleNamespace(compaction=SimpleNamespace(auto=True, reserved=12_345))

    monkeypatch.setattr(ConfigManager, "get", classmethod(fake_get_config))

    tokens = TokenUsage(input=58_000, output=0, reasoning=0, cache_read=0, cache_write=0, total=58_000)
    model = ProcessedModelInfo(
        id="m1",
        provider_id="openai",
        name="m1",
        api_id="m1",
        limit=ModelLimit(context=100_000, input=70_000, output=10_000),
    )

    assert await SessionCompaction.is_overflow(tokens=tokens, model=model) is True


def _conversation_with_tool_output(output: str) -> list[WithParts]:
    return [
        WithParts(
            info=MessageInfo(id="m_user_old", session_id="s1", role="user", time=MessageTime(created=1)),
            parts=[TextPart(id="p1", session_id="s1", message_id="m_user_old", text="old")],
        ),
        WithParts(
            info=MessageInfo(id="m_assistant_old", session_id="s1", role="assistant", time=MessageTime(created=2)),
            parts=[
                ToolPart(
                    id="p_tool",
                    session_id="s1",
                    message_id="m_assistant_old",
                    tool="bash",
                    call_id="call_1",
                    state=ToolState(
                        status="completed",
                        input={"command": "echo"},
                        output=output,
                        time=ToolStateTime(start=2, end=3),
                    ),
                )
            ],
        ),
        WithParts(
            info=MessageInfo(id="m_user_mid", session_id="s1", role="user", time=MessageTime(created=4)),
            parts=[TextPart(id="p2", session_id="s1", message_id="m_user_mid", text="mid")],
        ),
        WithParts(
            info=MessageInfo(id="m_assistant_mid", session_id="s1", role="assistant", time=MessageTime(created=5)),
            parts=[TextPart(id="p3", session_id="s1", message_id="m_assistant_mid", text="mid")],
        ),
        WithParts(
            info=MessageInfo(id="m_user_new", session_id="s1", role="user", time=MessageTime(created=6)),
            parts=[TextPart(id="p4", session_id="s1", message_id="m_user_new", text="new")],
        ),
        WithParts(
            info=MessageInfo(id="m_assistant_new", session_id="s1", role="assistant", time=MessageTime(created=7)),
            parts=[TextPart(id="p5", session_id="s1", message_id="m_assistant_new", text="new")],
        ),
    ]


@pytest.mark.anyio
async def test_prune_uses_token_estimate_not_utf8_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # This is ~90KB UTF-8 but only ~7.5K estimated tokens.
    output = "你" * 30_000
    messages = _conversation_with_tool_output(output)
    updated_parts: list[ToolPart] = []

    async def fake_get_config(cls):
        return SimpleNamespace(compaction=SimpleNamespace(prune=True))

    async def fake_messages(cls, *, session_id: str):
        assert session_id == "s1"
        return messages

    async def fake_update_part(cls, part):
        updated_parts.append(part)

    monkeypatch.setattr(ConfigManager, "get", classmethod(fake_get_config))
    monkeypatch.setattr(Session, "messages", classmethod(fake_messages))
    monkeypatch.setattr(Session, "update_part", classmethod(fake_update_part))

    await SessionCompaction.prune(session_id="s1")
    assert updated_parts == []


@pytest.mark.anyio
async def test_prune_marks_very_large_historical_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = "x" * 200_000
    messages = _conversation_with_tool_output(output)
    updated_parts: list[ToolPart] = []

    async def fake_get_config(cls):
        return SimpleNamespace(compaction=SimpleNamespace(prune=True))

    async def fake_messages(cls, *, session_id: str):
        assert session_id == "s1"
        return messages

    async def fake_update_part(cls, part):
        updated_parts.append(part)

    monkeypatch.setattr(ConfigManager, "get", classmethod(fake_get_config))
    monkeypatch.setattr(Session, "messages", classmethod(fake_messages))
    monkeypatch.setattr(Session, "update_part", classmethod(fake_update_part))

    await SessionCompaction.prune(session_id="s1")
    assert len(updated_parts) == 1
    assert updated_parts[0].state.time.compacted is not None
