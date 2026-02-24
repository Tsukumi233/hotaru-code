import pytest
from pydantic import BaseModel

from hotaru.agent.agent import AgentInfo, AgentMode
from hotaru.permission import RejectedError
from hotaru.project import Instance
from hotaru.provider.sdk.anthropic import ToolCall
from hotaru.session.llm import LLM, StreamChunk
from hotaru.session.processor import SessionProcessor
from hotaru.tool.registry import ToolRegistry
from hotaru.tool.tool import Tool, ToolContext, ToolResult
from tests.helpers import fake_agents, fake_app


@pytest.mark.anyio
async def test_processor_disables_tools_when_agent_step_limit_reached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}

    async def fake_stream(cls, stream_input):
        captured["tools"] = stream_input.tools
        captured["messages"] = stream_input.messages
        yield StreamChunk(type="text", text="Step limit reached summary.")

    async def fake_get_agent(name: str, **_kw):
        return AgentInfo(
            name=name,
            mode=AgentMode.PRIMARY,
            permission=[],
            steps=1,
            options={},
        )

    monkeypatch.setattr(LLM, "stream", classmethod(fake_stream))

    processor = SessionProcessor(
        app=fake_app(agents=fake_agents(get=fake_get_agent)),
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
    registry = ToolRegistry()

    async def probe_execute(_params: _ProbeParams, _ctx: ToolContext) -> ToolResult:
        # Fails without Instance context.
        return ToolResult(title="probe", output=Instance.directory())

    registry.register(
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

    async def fake_get_agent(name: str, **_kw):
        return AgentInfo(
            name=name,
            mode=AgentMode.PRIMARY,
            permission=[],
            options={},
        )

    monkeypatch.setattr(LLM, "stream", classmethod(fake_stream))

    processor = SessionProcessor(
        app=fake_app(agents=fake_agents(get=fake_get_agent), tools=registry),
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
    registry = ToolRegistry()

    class _MetaParams(BaseModel):
        pass

    async def meta_execute(_params: _MetaParams, ctx: ToolContext) -> ToolResult:
        ctx.metadata(title="Probe running", metadata={"progress": "half"})
        return ToolResult(title="Probe done", output="ok", metadata={"result": 1})

    registry.register(
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

    async def fake_get_agent(name: str, **_kw):
        return AgentInfo(
            name=name,
            mode=AgentMode.PRIMARY,
            permission=[],
            options={},
        )

    monkeypatch.setattr(LLM, "stream", classmethod(fake_stream))

    updates = []

    processor = SessionProcessor(
        app=fake_app(agents=fake_agents(get=fake_get_agent), tools=registry),
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


@pytest.mark.anyio
async def test_processor_uses_assistant_and_tool_call_ids_in_tool_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = ToolRegistry()
    captured: dict[str, str] = {}

    class _ProbeIDsParams(BaseModel):
        pass

    async def probe_ids_execute(_params: _ProbeIDsParams, ctx: ToolContext) -> ToolResult:
        captured["message_id"] = ctx.message_id
        captured["call_id"] = str(ctx.call_id)
        return ToolResult(title="ok", output="ok")

    registry.register(
        Tool.define(
            tool_id="probe_ids",
            description="Probe IDs",
            parameters_type=_ProbeIDsParams,
            execute_fn=probe_ids_execute,
            auto_truncate=False,
        )
    )

    async def fake_stream(cls, _stream_input):
        yield StreamChunk(type="tool_call_start", tool_call_id="call_probe_ids", tool_call_name="probe_ids")
        yield StreamChunk(
            type="tool_call_end",
            tool_call=ToolCall(id="call_probe_ids", name="probe_ids", input={}),
        )

    async def fake_get_agent(name: str, **_kw):
        return AgentInfo(name=name, mode=AgentMode.PRIMARY, permission=[], options={})

    monkeypatch.setattr(LLM, "stream", classmethod(fake_stream))

    processor = SessionProcessor(
        app=fake_app(agents=fake_agents(get=fake_get_agent), tools=registry),
        session_id="ses_ids",
        model_id="model",
        provider_id="provider",
        agent="build",
        cwd="/tmp",
        worktree="/tmp",
    )

    await processor.process_step(
        assistant_message_id="msg_assistant_1",
        tool_definitions=[
            {
                "type": "function",
                "function": {
                    "name": "probe_ids",
                    "description": "Probe IDs",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    )

    assert captured["message_id"] == "msg_assistant_1"
    assert captured["call_id"] == "call_probe_ids"


@pytest.mark.anyio
async def test_processor_stops_turn_when_tool_permission_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = ToolRegistry()

    class _RejectParams(BaseModel):
        pass

    async def reject_execute(_params: _RejectParams, _ctx: ToolContext) -> ToolResult:
        raise RejectedError()

    registry.register(
        Tool.define(
            tool_id="reject_tool",
            description="Reject tool",
            parameters_type=_RejectParams,
            execute_fn=reject_execute,
            auto_truncate=False,
        )
    )

    async def fake_stream(cls, _stream_input):
        yield StreamChunk(type="tool_call_start", tool_call_id="call_reject", tool_call_name="reject_tool")
        yield StreamChunk(
            type="tool_call_end",
            tool_call=ToolCall(id="call_reject", name="reject_tool", input={}),
        )

    async def fake_get_agent(name: str, **_kw):
        return AgentInfo(name=name, mode=AgentMode.PRIMARY, permission=[], options={})

    monkeypatch.setattr(LLM, "stream", classmethod(fake_stream))

    processor = SessionProcessor(
        app=fake_app(agents=fake_agents(get=fake_get_agent), tools=registry),
        session_id="ses_reject",
        model_id="model",
        provider_id="provider",
        agent="build",
        cwd="/tmp",
        worktree="/tmp",
    )

    result = await processor.process_step(
        tool_definitions=[
            {
                "type": "function",
                "function": {
                    "name": "reject_tool",
                    "description": "Reject tool",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    )

    assert result.status == "stop"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].status == "error"
    assert "rejected permission" in str(result.tool_calls[0].error).lower()


@pytest.mark.anyio
async def test_processor_can_continue_loop_on_deny_when_config_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = ToolRegistry()

    class _RejectParams(BaseModel):
        pass

    async def reject_execute(_params: _RejectParams, _ctx: ToolContext) -> ToolResult:
        raise RejectedError()

    registry.register(
        Tool.define(
            tool_id="reject_tool",
            description="Reject tool",
            parameters_type=_RejectParams,
            execute_fn=reject_execute,
            auto_truncate=False,
        )
    )

    async def fake_stream(cls, _stream_input):
        yield StreamChunk(type="tool_call_start", tool_call_id="call_reject", tool_call_name="reject_tool")
        yield StreamChunk(
            type="tool_call_end",
            tool_call=ToolCall(id="call_reject", name="reject_tool", input={}),
        )

    async def fake_get_agent(name: str, **_kw):
        return AgentInfo(name=name, mode=AgentMode.PRIMARY, permission=[], options={})

    async def fake_get_config(cls):  # type: ignore[no-untyped-def]
        return type("Cfg", (), {"continue_loop_on_deny": True})()

    monkeypatch.setattr(LLM, "stream", classmethod(fake_stream))
    monkeypatch.setattr("hotaru.core.config.ConfigManager.get", classmethod(fake_get_config))

    processor = SessionProcessor(
        app=fake_app(agents=fake_agents(get=fake_get_agent), tools=registry),
        session_id="ses_reject_continue",
        model_id="model",
        provider_id="provider",
        agent="build",
        cwd="/tmp",
        worktree="/tmp",
    )

    result = await processor.process_step(
        tool_definitions=[
            {
                "type": "function",
                "function": {
                    "name": "reject_tool",
                    "description": "Reject tool",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    )

    assert result.status == "continue"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].status == "error"


@pytest.mark.anyio
async def test_processor_emits_reasoning_callbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_stream(cls, _stream_input):
        yield StreamChunk(type="reasoning_start", reasoning_id="r1")
        yield StreamChunk(type="reasoning_delta", reasoning_id="r1", reasoning_text="hello")
        yield StreamChunk(type="reasoning_end", reasoning_id="r1")
        yield StreamChunk(type="text", text="done")
        yield StreamChunk(type="message_delta", stop_reason="stop")

    async def fake_get_agent(name: str, **_kw):
        return AgentInfo(name=name, mode=AgentMode.PRIMARY, permission=[], options={})

    monkeypatch.setattr(LLM, "stream", classmethod(fake_stream))

    processor = SessionProcessor(
        app=fake_app(agents=fake_agents(get=fake_get_agent)),
        session_id="ses_reasoning",
        model_id="model",
        provider_id="provider",
        agent="build",
        cwd="/tmp",
        worktree="/tmp",
    )

    events: list[tuple[str, str]] = []
    await processor.process_step(
        on_reasoning_start=lambda rid, _meta: events.append(("start", str(rid))),
        on_reasoning_delta=lambda rid, text, _meta: events.append(("delta", f"{rid}:{text}")),
        on_reasoning_end=lambda rid, _meta: events.append(("end", str(rid))),
    )

    assert events[0] == ("start", "r1")
    assert ("delta", "r1:hello") in events
    assert events[-1] == ("end", "r1")


@pytest.mark.anyio
async def test_processor_includes_reasoning_text_in_assistant_tool_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_stream(cls, _stream_input):
        yield StreamChunk(type="reasoning_start", reasoning_id="r1")
        yield StreamChunk(type="reasoning_delta", reasoning_id="r1", reasoning_text="plan step")
        yield StreamChunk(type="reasoning_end", reasoning_id="r1")
        yield StreamChunk(type="tool_call_start", tool_call_id="call_1", tool_call_name="unknown_tool")
        yield StreamChunk(
            type="tool_call_end",
            tool_call=ToolCall(id="call_1", name="unknown_tool", input={}),
        )

    async def fake_get_agent(name: str, **_kw):
        return AgentInfo(name=name, mode=AgentMode.PRIMARY, permission=[], options={})

    monkeypatch.setattr(LLM, "stream", classmethod(fake_stream))

    processor = SessionProcessor(
        app=fake_app(agents=fake_agents(get=fake_get_agent)),
        session_id="ses_reasoning_tools",
        model_id="model",
        provider_id="provider",
        agent="build",
        cwd="/tmp",
        worktree="/tmp",
    )

    await processor.process_step(
        tool_definitions=[
            {
                "type": "function",
                "function": {
                    "name": "unknown_tool",
                    "description": "Unknown tool for failure path",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    )

    assistant = next(msg for msg in processor.messages if msg.get("role") == "assistant")
    assert assistant["reasoning_text"] == "plan step"


@pytest.mark.anyio
async def test_processor_routes_unknown_tool_to_resolver_mcp_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_agent(name: str, **_kw):
        return AgentInfo(name=name, mode=AgentMode.PRIMARY, permission=[], options={})

    async def fake_mcp_info(cls, tool_id: str):
        if tool_id != "mcp_demo":
            return None
        return {
            "client": "demo",
            "name": "echo",
            "timeout": 30.0,
        }

    captured: dict[str, object] = {}

    async def fake_exec_mcp(
        self,
        tool_id: str,
        mcp_info: dict,
        tool_input: dict,
    ) -> dict:
        captured["tool_id"] = tool_id
        captured["mcp_info"] = mcp_info
        captured["tool_input"] = tool_input
        return {"output": "ok", "title": "", "metadata": {}}

    from types import SimpleNamespace
    tools_stub = SimpleNamespace(get=lambda _tool_id: None)

    monkeypatch.setattr("hotaru.session.processor.ToolResolver.mcp_info", classmethod(fake_mcp_info))
    monkeypatch.setattr(SessionProcessor, "_execute_mcp_tool", fake_exec_mcp)

    processor = SessionProcessor(
        app=fake_app(agents=fake_agents(get=fake_get_agent), tools=tools_stub),
        session_id="ses_mcp_lookup",
        model_id="model",
        provider_id="provider",
        agent="build",
        cwd="/tmp",
        worktree="/tmp",
    )

    result = await processor._execute_tool("mcp_demo", {"query": "hello"})

    assert result["output"] == "ok"
    assert captured["tool_id"] == "mcp_demo"
    assert captured["mcp_info"] == {"client": "demo", "name": "echo", "timeout": 30.0}
    assert captured["tool_input"] == {"query": "hello"}


@pytest.mark.anyio
async def test_processor_reraises_unexpected_turn_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_stream(cls, _stream_input):
        yield StreamChunk(type="text", text="hello")

    async def fake_get_agent(name: str, **_kw):
        return AgentInfo(name=name, mode=AgentMode.PRIMARY, permission=[], options={})

    monkeypatch.setattr(LLM, "stream", classmethod(fake_stream))

    processor = SessionProcessor(
        app=fake_app(agents=fake_agents(get=fake_get_agent)),
        session_id="ses_turn_type_error",
        model_id="model",
        provider_id="provider",
        agent="build",
        cwd="/tmp",
        worktree="/tmp",
    )

    with pytest.raises(TypeError, match="broken callback"):
        await processor.process_step(on_text=lambda _text: (_ for _ in ()).throw(TypeError("broken callback")))


@pytest.mark.anyio
async def test_processor_marks_turn_timeout_as_recoverable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_stream(cls, _stream_input):
        raise TimeoutError("upstream timeout")
        yield StreamChunk(type="text", text="never")

    async def fake_get_agent(name: str, **_kw):
        return AgentInfo(name=name, mode=AgentMode.PRIMARY, permission=[], options={})

    monkeypatch.setattr(LLM, "stream", classmethod(fake_stream))

    processor = SessionProcessor(
        app=fake_app(agents=fake_agents(get=fake_get_agent)),
        session_id="ses_turn_timeout",
        model_id="model",
        provider_id="provider",
        agent="build",
        cwd="/tmp",
        worktree="/tmp",
    )

    result = await processor.process_step()

    assert result.status == "error"
    assert result.error == "upstream timeout"


@pytest.mark.anyio
async def test_processor_sanitizes_control_chars_without_truncating_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_stream(cls, _stream_input):
        yield StreamChunk(type="text", text="健康状态管理 - 启动\r")
        yield StreamChunk(type="text", text="并发初始化")
        yield StreamChunk(type="message_delta", stop_reason="stop")

    async def fake_get_agent(name: str, **_kw):
        return AgentInfo(name=name, mode=AgentMode.PRIMARY, permission=[], options={})

    monkeypatch.setattr(LLM, "stream", classmethod(fake_stream))

    processor = SessionProcessor(
        app=fake_app(agents=fake_agents(get=fake_get_agent)),
        session_id="ses_sanitize_text",
        model_id="model",
        provider_id="provider",
        agent="build",
        cwd="/tmp",
        worktree="/tmp",
    )

    seen: list[str] = []
    result = await processor.process_step(on_text=lambda text: seen.append(text))

    assert result.text == "健康状态管理 - 启动\ufffd并发初始化"
    assert "".join(seen) == "健康状态管理 - 启动\ufffd并发初始化"
