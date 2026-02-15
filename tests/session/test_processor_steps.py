import pytest
from pydantic import BaseModel

from hotaru.agent.agent import AgentInfo, AgentMode
from hotaru.project import Instance
from hotaru.provider.sdk.anthropic import ToolCall
from hotaru.session.llm import LLM, StreamChunk
from hotaru.session.processor import SessionProcessor
from hotaru.tool.registry import ToolRegistry
from hotaru.tool.tool import Tool, ToolContext, ToolResult


@pytest.mark.anyio
async def test_processor_disables_tools_when_agent_step_limit_reached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}

    async def fake_stream(cls, stream_input):
        captured["tools"] = stream_input.tools
        captured["messages"] = stream_input.messages
        yield StreamChunk(type="text", text="Step limit reached summary.")

    async def fake_get_agent(cls, name: str):
        return AgentInfo(
            name=name,
            mode=AgentMode.PRIMARY,
            permission=[],
            steps=1,
            options={},
        )

    monkeypatch.setattr(LLM, "stream", classmethod(fake_stream))
    monkeypatch.setattr("hotaru.agent.agent.Agent.get", classmethod(fake_get_agent))

    processor = SessionProcessor(
        session_id="ses_test",
        model_id="model",
        provider_id="provider",
        agent="build",
        cwd="/tmp",
        worktree="/tmp",
    )

    result = await processor.process(user_message="Please analyze this code.")

    assert result.status == "stop"
    assert captured["tools"] is None
    assert any(
        msg.get("role") == "assistant" and "MAXIMUM STEPS REACHED" in str(msg.get("content", ""))
        for msg in captured["messages"]
    )


class _ProbeParams(BaseModel):
    pass


@pytest.mark.anyio
async def test_processor_binds_instance_context_for_tool_execution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    ToolRegistry.reset()

    async def probe_execute(_params: _ProbeParams, _ctx: ToolContext) -> ToolResult:
        # Fails without Instance context.
        return ToolResult(title="probe", output=Instance.directory())

    ToolRegistry.register(
        Tool.define(
            tool_id="ctx_probe",
            description="Context probe",
            parameters_type=_ProbeParams,
            execute_fn=probe_execute,
            auto_truncate=False,
        )
    )

    turn_count = 0

    async def fake_stream(cls, _stream_input):
        nonlocal turn_count
        turn_count += 1
        if turn_count == 1:
            yield StreamChunk(
                type="tool_call_start",
                tool_call_id="call_ctx_probe",
                tool_call_name="ctx_probe",
            )
            yield StreamChunk(
                type="tool_call_end",
                tool_call=ToolCall(id="call_ctx_probe", name="ctx_probe", input={}),
            )
            return
        yield StreamChunk(type="text", text="done")

    async def fake_get_agent(cls, name: str):
        return AgentInfo(
            name=name,
            mode=AgentMode.PRIMARY,
            permission=[],
            options={},
        )

    monkeypatch.setattr(LLM, "stream", classmethod(fake_stream))
    monkeypatch.setattr("hotaru.agent.agent.Agent.get", classmethod(fake_get_agent))

    processor = SessionProcessor(
        session_id="ses_ctx",
        model_id="model",
        provider_id="provider",
        agent="build",
        cwd=str(tmp_path),
        worktree=str(tmp_path),
    )

    result = await processor.process(user_message="probe")

    assert result.status == "stop"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].status == "completed"
    assert result.tool_calls[0].output == str(tmp_path.resolve())


@pytest.mark.anyio
async def test_processor_emits_tool_updates_with_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ToolRegistry.reset()

    class _MetaParams(BaseModel):
        pass

    async def meta_execute(_params: _MetaParams, ctx: ToolContext) -> ToolResult:
        ctx.metadata(title="Probe running", metadata={"progress": "half"})
        return ToolResult(title="Probe done", output="ok", metadata={"result": 1})

    ToolRegistry.register(
        Tool.define(
            tool_id="meta_probe",
            description="Metadata probe",
            parameters_type=_MetaParams,
            execute_fn=meta_execute,
            auto_truncate=False,
        )
    )

    async def fake_stream(cls, _stream_input):
        yield StreamChunk(
            type="tool_call_start",
            tool_call_id="call_meta_probe",
            tool_call_name="meta_probe",
        )
        yield StreamChunk(
            type="tool_call_end",
            tool_call=ToolCall(id="call_meta_probe", name="meta_probe", input={}),
        )

    async def fake_get_agent(cls, name: str):
        return AgentInfo(
            name=name,
            mode=AgentMode.PRIMARY,
            permission=[],
            options={},
        )

    monkeypatch.setattr(LLM, "stream", classmethod(fake_stream))
    monkeypatch.setattr("hotaru.agent.agent.Agent.get", classmethod(fake_get_agent))

    updates = []

    processor = SessionProcessor(
        session_id="ses_updates",
        model_id="model",
        provider_id="provider",
        agent="build",
        cwd="/tmp",
        worktree="/tmp",
    )

    await processor.process_step(
        on_tool_update=lambda payload: updates.append(payload),
        tool_definitions=[
            {
                "type": "function",
                "function": {
                    "name": "meta_probe",
                    "description": "Metadata probe",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    )

    statuses = [item.get("status") for item in updates]
    assert "pending" in statuses
    assert "running" in statuses
    assert "completed" in statuses
    assert any(item.get("metadata", {}).get("progress") == "half" for item in updates)
    assert any(item.get("title") == "Probe done" for item in updates)
