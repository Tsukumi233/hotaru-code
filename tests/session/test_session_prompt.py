from pathlib import Path
import shutil
import subprocess

import pytest

from hotaru.agent.agent import AgentInfo, AgentMode
from hotaru.core.id import Identifier
from hotaru.core.global_paths import GlobalPath
from hotaru.provider.models import ModelLimit
from hotaru.provider.provider import ProcessedModelInfo
from hotaru.provider.sdk.anthropic import ToolCall
from hotaru.session import Session, SessionPrompt
from hotaru.session.compaction import SessionCompaction
from hotaru.session.llm import LLM, StreamChunk
from hotaru.session.message_store import (
    CompactionPart,
    MessageInfo,
    MessageTime,
    ModelRef,
)
from hotaru.storage import Storage


def _setup_storage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(GlobalPath, "data", classmethod(lambda cls: str(data_dir)))
    Storage.reset()


@pytest.mark.anyio
async def test_session_prompt_writes_structured_messages(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _setup_storage(monkeypatch, tmp_path)

    async def fake_stream(cls, _stream_input):
        yield StreamChunk(type="text", text="done")
        yield StreamChunk(type="message_delta", usage={"input_tokens": 9, "output_tokens": 3})

    async def fake_get_agent(cls, name: str):
        return AgentInfo(name=name, mode=AgentMode.PRIMARY, permission=[], options={})

    monkeypatch.setattr(LLM, "stream", classmethod(fake_stream))
    monkeypatch.setattr("hotaru.agent.agent.Agent.get", classmethod(fake_get_agent))

    session = await Session.create(project_id="p1", agent="build", directory=str(tmp_path))
    result = await SessionPrompt.prompt(
        session_id=session.id,
        content="hello",
        provider_id="openai",
        model_id="gpt-5",
        agent="build",
        cwd=str(tmp_path),
        worktree=str(tmp_path),
        resume_history=True,
        auto_compaction=False,
    )

    assert result.text == "done"

    structured = await Session.messages(session_id=session.id)
    assert len(structured) == 2
    assert structured[0].info.role == "user"
    assert structured[1].info.role == "assistant"
    assert structured[1].info.tokens.input == 9
    assert structured[1].info.tokens.output == 3
    part_types = [getattr(part, "type", "") for part in structured[1].parts]
    assert "step-start" in part_types
    assert "step-finish" in part_types


@pytest.mark.anyio
async def test_session_prompt_persists_reasoning_parts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _setup_storage(monkeypatch, tmp_path)

    async def fake_stream(cls, _stream_input):
        yield StreamChunk(type="reasoning_start", reasoning_id="r1")
        yield StreamChunk(type="reasoning_delta", reasoning_id="r1", reasoning_text="think ")
        yield StreamChunk(type="reasoning_delta", reasoning_id="r1", reasoning_text="done  ")
        yield StreamChunk(type="reasoning_end", reasoning_id="r1")
        yield StreamChunk(type="text", text="answer")
        yield StreamChunk(type="message_delta", usage={"input_tokens": 4, "output_tokens": 2})

    async def fake_get_agent(cls, name: str):
        return AgentInfo(name=name, mode=AgentMode.PRIMARY, permission=[], options={})

    monkeypatch.setattr(LLM, "stream", classmethod(fake_stream))
    monkeypatch.setattr("hotaru.agent.agent.Agent.get", classmethod(fake_get_agent))

    session = await Session.create(project_id="p1", agent="build", directory=str(tmp_path))
    await SessionPrompt.prompt(
        session_id=session.id,
        content="hello",
        provider_id="openai",
        model_id="gpt-5",
        agent="build",
        cwd=str(tmp_path),
        worktree=str(tmp_path),
        resume_history=True,
        auto_compaction=False,
    )

    structured = await Session.messages(session_id=session.id)
    assistant = next(msg for msg in structured if msg.info.role == "assistant")
    reasoning_parts = [part for part in assistant.parts if getattr(part, "type", "") == "reasoning"]
    assert len(reasoning_parts) == 1
    assert reasoning_parts[0].text == "think done"
    assert reasoning_parts[0].time.end is not None


@pytest.mark.anyio
async def test_session_prompt_non_git_workspace_skips_patch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _setup_storage(monkeypatch, tmp_path)

    target = tmp_path / "hello.txt"

    async def fake_stream(cls, _stream_input):
        target.write_text("world")
        yield StreamChunk(type="text", text="done")
        yield StreamChunk(type="message_delta", usage={"input_tokens": 2, "output_tokens": 1})

    async def fake_get_agent(cls, name: str):
        return AgentInfo(name=name, mode=AgentMode.PRIMARY, permission=[], options={})

    monkeypatch.setattr(LLM, "stream", classmethod(fake_stream))
    monkeypatch.setattr("hotaru.agent.agent.Agent.get", classmethod(fake_get_agent))

    session = await Session.create(project_id="p1", agent="build", directory=str(tmp_path))
    await SessionPrompt.prompt(
        session_id=session.id,
        content="write file",
        provider_id="openai",
        model_id="gpt-5",
        agent="build",
        cwd=str(tmp_path),
        worktree=str(tmp_path),
        resume_history=True,
        auto_compaction=False,
    )

    structured = await Session.messages(session_id=session.id)
    assistant = next(msg for msg in structured if msg.info.role == "assistant")
    step_start = next(part for part in assistant.parts if getattr(part, "type", "") == "step-start")
    step_finish = next(part for part in assistant.parts if getattr(part, "type", "") == "step-finish")
    assert step_start.snapshot is None
    assert step_finish.snapshot is None
    assert not any(getattr(part, "type", "") == "patch" for part in assistant.parts)


@pytest.mark.anyio
async def test_session_prompt_git_workspace_records_patch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _setup_storage(monkeypatch, tmp_path)
    if not shutil.which("git"):
        pytest.skip("git is not available")

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)

    target = tmp_path / "hello.txt"
    target.write_text("before")

    async def fake_stream(cls, _stream_input):
        target.write_text("after")
        yield StreamChunk(type="text", text="done")
        yield StreamChunk(type="message_delta", usage={"input_tokens": 2, "output_tokens": 1})

    async def fake_get_agent(cls, name: str):
        return AgentInfo(name=name, mode=AgentMode.PRIMARY, permission=[], options={})

    monkeypatch.setattr(LLM, "stream", classmethod(fake_stream))
    monkeypatch.setattr("hotaru.agent.agent.Agent.get", classmethod(fake_get_agent))

    session = await Session.create(project_id="p1", agent="build", directory=str(tmp_path))
    await SessionPrompt.prompt(
        session_id=session.id,
        content="write file",
        provider_id="openai",
        model_id="gpt-5",
        agent="build",
        cwd=str(tmp_path),
        worktree=str(tmp_path),
        resume_history=True,
        auto_compaction=False,
    )

    structured = await Session.messages(session_id=session.id)
    assistant = next(msg for msg in structured if msg.info.role == "assistant")
    patch_parts = [part for part in assistant.parts if getattr(part, "type", "") == "patch"]
    assert len(patch_parts) == 1
    assert str(target.resolve()) in patch_parts[0].files


@pytest.mark.anyio
async def test_session_prompt_computes_step_and_message_cost(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _setup_storage(monkeypatch, tmp_path)

    async def fake_stream(cls, _stream_input):
        yield StreamChunk(type="text", text="priced")
        yield StreamChunk(
            type="message_delta",
            usage={
                "input_tokens": 1000,
                "output_tokens": 200,
                "reasoning_tokens": 50,
                "cache_read_tokens": 300,
                "cache_write_tokens": 100,
            },
        )

    async def fake_get_agent(cls, name: str):
        return AgentInfo(name=name, mode=AgentMode.PRIMARY, permission=[], options={})

    async def fake_get_model(cls, provider_id: str, model_id: str):
        return ProcessedModelInfo(
            id=model_id,
            provider_id=provider_id,
            name=model_id,
            api_id=model_id,
            cost={
                "input": 1.0,
                "output": 2.0,
                "cache_read": 0.5,
                "cache_write": 1.5,
            },
            limit=ModelLimit(context=128_000, output=4096),
        )

    monkeypatch.setattr(LLM, "stream", classmethod(fake_stream))
    monkeypatch.setattr("hotaru.agent.agent.Agent.get", classmethod(fake_get_agent))
    monkeypatch.setattr("hotaru.provider.provider.Provider.get_model", classmethod(fake_get_model))

    session = await Session.create(project_id="p1", agent="build", directory=str(tmp_path))
    await SessionPrompt.prompt(
        session_id=session.id,
        content="hello",
        provider_id="openai",
        model_id="gpt-5",
        agent="build",
        cwd=str(tmp_path),
        worktree=str(tmp_path),
        resume_history=True,
        auto_compaction=False,
    )

    structured = await Session.messages(session_id=session.id)
    assistant = next(msg for msg in structured if msg.info.role == "assistant")
    expected = (
        (1000 * 1.0)
        + (200 * 2.0)
        + (300 * 0.5)
        + (100 * 1.5)
        + (50 * 2.0)
    ) / 1_000_000
    assert assistant.info.cost == pytest.approx(expected)
    step_finish = next(part for part in assistant.parts if getattr(part, "type", "") == "step-finish")
    assert step_finish.cost == pytest.approx(expected)


@pytest.mark.anyio
async def test_session_prompt_respects_assistant_message_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _setup_storage(monkeypatch, tmp_path)

    async def fake_stream(cls, _stream_input):
        yield StreamChunk(type="text", text="ok")
        yield StreamChunk(type="message_delta", usage={"input_tokens": 1, "output_tokens": 1})

    async def fake_get_agent(cls, name: str):
        return AgentInfo(name=name, mode=AgentMode.PRIMARY, permission=[], options={})

    monkeypatch.setattr(LLM, "stream", classmethod(fake_stream))
    monkeypatch.setattr("hotaru.agent.agent.Agent.get", classmethod(fake_get_agent))

    session = await Session.create(project_id="p1", agent="build", directory=str(tmp_path))
    expected_assistant_id = "message_custom_assistant"
    result = await SessionPrompt.prompt(
        session_id=session.id,
        content="hello",
        provider_id="openai",
        model_id="gpt-5",
        agent="build",
        cwd=str(tmp_path),
        worktree=str(tmp_path),
        resume_history=True,
        auto_compaction=False,
        assistant_message_id=expected_assistant_id,
    )

    assert result.assistant_message_id == expected_assistant_id

    structured = await Session.messages(session_id=session.id)
    assistant_structured = next(msg for msg in structured if msg.info.role == "assistant")
    assert assistant_structured.info.id == expected_assistant_id


@pytest.mark.anyio
async def test_session_prompt_compaction_summary_and_continue(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _setup_storage(monkeypatch, tmp_path)

    stream_calls = {"count": 0}

    async def fake_stream(cls, _stream_input):
        stream_calls["count"] += 1
        if stream_calls["count"] == 1:
            yield StreamChunk(type="tool_call_start", tool_call_id="call_1", tool_call_name="unknown_tool")
            yield StreamChunk(type="tool_call_end", tool_call=ToolCall(id="call_1", name="unknown_tool", input={}))
            yield StreamChunk(type="message_delta", usage={"input_tokens": 95_000, "output_tokens": 500})
            return
        if stream_calls["count"] == 2:
            yield StreamChunk(type="text", text="compacted summary")
            yield StreamChunk(type="message_delta", usage={"input_tokens": 100, "output_tokens": 30})
            return
        yield StreamChunk(type="text", text="final")
        yield StreamChunk(type="message_delta", usage={"input_tokens": 5, "output_tokens": 2})

    async def fake_get_agent(cls, name: str):
        if name == "compaction":
            return AgentInfo(
                name="compaction",
                mode=AgentMode.PRIMARY,
                permission=[{"permission": "*", "pattern": "*", "action": "deny"}],
                options={},
                prompt="Summarize only.",
            )
        return AgentInfo(name=name, mode=AgentMode.PRIMARY, permission=[], options={})

    async def fake_get_model(cls, provider_id: str, model_id: str):
        return ProcessedModelInfo(
            id=model_id,
            provider_id=provider_id,
            name=model_id,
            api_id=model_id,
            limit=ModelLimit(context=128_000, output=4_096),
        )

    overflow_checks = {"count": 0}

    async def fake_is_overflow(cls, *, tokens, model):
        overflow_checks["count"] += 1
        return overflow_checks["count"] == 1

    monkeypatch.setattr(LLM, "stream", classmethod(fake_stream))
    monkeypatch.setattr("hotaru.agent.agent.Agent.get", classmethod(fake_get_agent))
    monkeypatch.setattr("hotaru.provider.provider.Provider.get_model", classmethod(fake_get_model))
    monkeypatch.setattr(SessionCompaction, "is_overflow", classmethod(fake_is_overflow))

    session = await Session.create(project_id="p1", agent="build", directory=str(tmp_path))
    result = await SessionPrompt.prompt(
        session_id=session.id,
        content="ship it",
        provider_id="openai",
        model_id="gpt-5",
        agent="build",
        cwd=str(tmp_path),
        worktree=str(tmp_path),
        resume_history=True,
        auto_compaction=True,
    )

    assert result.text == "final"

    user_texts = [
        getattr(part, "text", "")
        for msg in (await Session.messages(session_id=session.id))
        if msg.info.role == "user"
        for part in msg.parts
        if getattr(part, "type", "") == "text"
    ]
    assert "What did we do so far?" in user_texts
    assert any("Continue if you have next steps" in text for text in user_texts)

    structured = await Session.messages(session_id=session.id)
    summary_messages = [m for m in structured if m.info.role == "assistant" and m.info.summary is True]
    assert len(summary_messages) == 1
    assert summary_messages[0].info.mode == "compaction"

    assistant_messages = [m for m in structured if m.info.role == "assistant"]
    assert assistant_messages[-1].info.id == result.assistant_message_id


@pytest.mark.anyio
async def test_session_prompt_handles_pending_compaction_on_resume(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _setup_storage(monkeypatch, tmp_path)

    async def fake_stream(cls, _stream_input):
        yield StreamChunk(type="text", text="resume summary")
        yield StreamChunk(type="message_delta", usage={"input_tokens": 12, "output_tokens": 4})

    async def fake_get_agent(cls, name: str):
        if name == "compaction":
            return AgentInfo(
                name="compaction",
                mode=AgentMode.PRIMARY,
                permission=[],
                options={},
            )
        return AgentInfo(name=name, mode=AgentMode.PRIMARY, permission=[], options={})

    monkeypatch.setattr(LLM, "stream", classmethod(fake_stream))
    monkeypatch.setattr("hotaru.agent.agent.Agent.get", classmethod(fake_get_agent))

    session = await Session.create(project_id="p1", agent="build", directory=str(tmp_path))
    pending_id = Identifier.ascending("message")
    await Session.update_message(
        MessageInfo(
            id=pending_id,
            session_id=session.id,
            role="user",
            agent="build",
            model=ModelRef(provider_id="openai", model_id="gpt-5"),
            time=MessageTime(created=1, completed=1),
        )
    )
    await Session.update_part(
        CompactionPart(
            id=Identifier.ascending("part"),
            session_id=session.id,
            message_id=pending_id,
            auto=False,
        )
    )

    result = await SessionPrompt.loop(
        session_id=session.id,
        provider_id="openai",
        model_id="gpt-5",
        agent="build",
        cwd=str(tmp_path),
        worktree=str(tmp_path),
        resume_history=True,
        auto_compaction=False,
    )

    assert result.result.status == "stop"
    assert result.text == ""

    structured = await Session.messages(session_id=session.id)
    summaries = [m for m in structured if m.info.role == "assistant" and m.info.summary is True]
    assert len(summaries) == 1
    assert summaries[0].info.parent_id == pending_id


@pytest.mark.anyio
async def test_session_prompt_structured_output_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _setup_storage(monkeypatch, tmp_path)

    async def fake_stream(cls, stream_input):
        tool_names = [item["function"]["name"] for item in (stream_input.tools or [])]
        assert "StructuredOutput" in tool_names
        assert stream_input.tool_choice == "required"
        yield StreamChunk(type="tool_call_start", tool_call_id="call_struct", tool_call_name="StructuredOutput")
        yield StreamChunk(
            type="tool_call_end",
            tool_call=ToolCall(id="call_struct", name="StructuredOutput", input={"answer": "done"}),
        )
        yield StreamChunk(type="message_delta", usage={"input_tokens": 8, "output_tokens": 2}, stop_reason="tool_calls")

    async def fake_get_agent(cls, name: str):
        return AgentInfo(name=name, mode=AgentMode.PRIMARY, permission=[], options={})

    monkeypatch.setattr(LLM, "stream", classmethod(fake_stream))
    monkeypatch.setattr("hotaru.agent.agent.Agent.get", classmethod(fake_get_agent))

    session = await Session.create(project_id="p1", agent="build", directory=str(tmp_path))
    result = await SessionPrompt.prompt(
        session_id=session.id,
        content="return structured",
        format={
            "type": "json_schema",
            "schema": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
            },
        },
        provider_id="openai",
        model_id="gpt-5",
        agent="build",
        cwd=str(tmp_path),
        worktree=str(tmp_path),
        auto_compaction=False,
    )

    assert result.result.status == "stop"
    assert result.result.error is None
    structured = await Session.messages(session_id=session.id)
    assistant = next(msg for msg in reversed(structured) if msg.info.role == "assistant")
    assert assistant.info.structured == {"answer": "done"}


@pytest.mark.anyio
async def test_session_prompt_structured_output_missing_tool_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _setup_storage(monkeypatch, tmp_path)

    async def fake_stream(cls, _stream_input):
        yield StreamChunk(type="text", text="plain response")
        yield StreamChunk(type="message_delta", usage={"input_tokens": 3, "output_tokens": 3}, stop_reason="stop")

    async def fake_get_agent(cls, name: str):
        return AgentInfo(name=name, mode=AgentMode.PRIMARY, permission=[], options={})

    monkeypatch.setattr(LLM, "stream", classmethod(fake_stream))
    monkeypatch.setattr("hotaru.agent.agent.Agent.get", classmethod(fake_get_agent))

    session = await Session.create(project_id="p1", agent="build", directory=str(tmp_path))
    result = await SessionPrompt.prompt(
        session_id=session.id,
        content="return structured",
        format={
            "type": "json_schema",
            "schema": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
            },
        },
        provider_id="openai",
        model_id="gpt-5",
        agent="build",
        cwd=str(tmp_path),
        worktree=str(tmp_path),
        auto_compaction=False,
    )

    assert result.result.status == "error"
    assert result.result.error == "Model did not produce structured output"
