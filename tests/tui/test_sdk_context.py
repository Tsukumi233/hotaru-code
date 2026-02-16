from types import SimpleNamespace
import inspect

import pytest

from hotaru.provider.provider import ProcessedModelInfo
from hotaru.tui.context.sdk import SDKContext


@pytest.mark.anyio
async def test_send_message_emits_tool_part_updates_without_truncation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    sdk = SDKContext(cwd=str(tmp_path))

    async def fake_ensure_project(self):
        self._project = SimpleNamespace(vcs="git")
        self._sandbox = str(tmp_path)

    async def fake_get_model(cls, provider_id: str, model_id: str):
        return ProcessedModelInfo(
            id=model_id,
            provider_id=provider_id,
            name=model_id,
            api_id=model_id,
        )

    async def fake_default_model(cls):
        return ("openai", "gpt-5")

    async def fake_session_get(cls, _session_id: str):
        return SimpleNamespace(agent="build")

    async def fake_session_update(cls, _session_id: str, **_kwargs):
        return SimpleNamespace(agent="build")

    async def fake_agent_get(cls, _name: str):
        return SimpleNamespace(mode="primary")

    async def fake_default_agent(cls):
        return "build"

    async def fake_system_prompt(cls, **_kwargs):
        return "system prompt"

    long_output = "x" * 1500

    async def fake_prompt(cls, **kwargs):
        on_tool_update = kwargs.get("on_tool_update")
        if on_tool_update:
            on_tool_update(
                {
                    "id": "call_tool_1",
                    "name": "bash",
                    "input_json": '{"command":"echo hi"}',
                    "input": {"command": "echo hi"},
                    "status": "running",
                    "output": "",
                    "error": None,
                    "title": "Running command",
                    "metadata": {"progress": "start"},
                    "attachments": [],
                    "start_time": 10,
                    "end_time": None,
                }
            )
            on_tool_update(
                {
                    "id": "call_tool_1",
                    "name": "bash",
                    "input_json": '{"command":"echo hi"}',
                    "input": {"command": "echo hi"},
                    "status": "completed",
                    "output": long_output,
                    "error": None,
                    "title": "Long output",
                    "metadata": {"progress": "done"},
                    "attachments": [],
                    "start_time": 10,
                    "end_time": 11,
                }
            )
        return SimpleNamespace(result=SimpleNamespace(error=None, usage={"input_tokens": 1}))

    monkeypatch.setattr(SDKContext, "_ensure_project", fake_ensure_project)
    monkeypatch.setattr("hotaru.provider.provider.Provider.get_model", classmethod(fake_get_model))
    monkeypatch.setattr("hotaru.provider.provider.Provider.default_model", classmethod(fake_default_model))
    monkeypatch.setattr("hotaru.session.session.Session.get", classmethod(fake_session_get))
    monkeypatch.setattr("hotaru.session.session.Session.update", classmethod(fake_session_update))
    monkeypatch.setattr("hotaru.agent.agent.Agent.get", classmethod(fake_agent_get))
    monkeypatch.setattr("hotaru.agent.agent.Agent.default_agent", classmethod(fake_default_agent))
    monkeypatch.setattr("hotaru.session.system.SystemPrompt.build_full_prompt", classmethod(fake_system_prompt))
    monkeypatch.setattr("hotaru.session.prompting.SessionPrompt.prompt", classmethod(fake_prompt))

    events = []
    async for event in sdk.send_message(
        session_id="session_1",
        content="hello",
        agent="build",
        model="openai/gpt-5",
    ):
        events.append(event)

    tool_updates = [
        event
        for event in events
        if event.get("type") == "message.part.updated"
        and (event.get("data", {}).get("part", {}) or {}).get("type") == "tool"
    ]
    assert len(tool_updates) >= 2

    completed = tool_updates[-1]["data"]["part"]
    assert completed["tool"] == "bash"
    assert completed["call_id"] == "call_tool_1"
    assert completed["state"]["status"] == "completed"
    assert completed["state"]["output"] == long_output
    assert completed["state"]["title"] == "Long output"
    assert completed["state"]["metadata"]["progress"] == "done"


@pytest.mark.anyio
async def test_compact_session_creates_manual_compaction_and_runs_loop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    sdk = SDKContext(cwd=str(tmp_path))

    async def fake_ensure_project(self):
        self._project = SimpleNamespace(vcs="git")
        self._sandbox = str(tmp_path)

    async def fake_session_get(cls, session_id: str):
        assert session_id == "session_1"
        return SimpleNamespace(agent="build", provider_id="openai", model_id="gpt-5")

    async def fake_get_model(cls, provider_id: str, model_id: str):
        return ProcessedModelInfo(
            id=model_id,
            provider_id=provider_id,
            name=model_id,
            api_id=model_id,
        )

    async def fake_system_prompt(cls, **_kwargs):
        return "system prompt"

    compaction_calls = {}

    async def fake_compaction_create(cls, **kwargs):
        compaction_calls.update(kwargs)
        return "message_compaction"

    async def fake_loop(cls, **kwargs):
        assert kwargs["session_id"] == "session_1"
        assert kwargs["resume_history"] is True
        assert kwargs["auto_compaction"] is False
        return SimpleNamespace(
            assistant_message_id="message_summary",
            text="summary",
            result=SimpleNamespace(status="stop", error=None, usage={"input_tokens": 10}),
        )

    monkeypatch.setattr(SDKContext, "_ensure_project", fake_ensure_project)
    monkeypatch.setattr("hotaru.session.session.Session.get", classmethod(fake_session_get))
    monkeypatch.setattr("hotaru.provider.provider.Provider.get_model", classmethod(fake_get_model))
    monkeypatch.setattr("hotaru.session.system.SystemPrompt.build_full_prompt", classmethod(fake_system_prompt))
    monkeypatch.setattr("hotaru.session.compaction.SessionCompaction.create", classmethod(fake_compaction_create))
    monkeypatch.setattr("hotaru.session.prompting.SessionPrompt.loop", classmethod(fake_loop))

    result = await sdk.compact_session(session_id="session_1")

    assert compaction_calls["session_id"] == "session_1"
    assert compaction_calls["agent"] == "build"
    assert compaction_calls["provider_id"] == "openai"
    assert compaction_calls["model_id"] == "gpt-5"
    assert compaction_calls["auto"] is False
    assert result["user_message_id"] == "message_compaction"
    assert result["assistant_message_id"] == "message_summary"
    assert result["status"] == "stop"
    assert result["error"] is None


@pytest.mark.anyio
async def test_send_message_emits_reasoning_and_step_part_updates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    sdk = SDKContext(cwd=str(tmp_path))

    async def fake_ensure_project(self):
        self._project = SimpleNamespace(vcs="git")
        self._sandbox = str(tmp_path)

    async def fake_get_model(cls, provider_id: str, model_id: str):
        return ProcessedModelInfo(
            id=model_id,
            provider_id=provider_id,
            name=model_id,
            api_id=model_id,
        )

    async def fake_default_model(cls):
        return ("openai", "gpt-5")

    async def fake_session_get(cls, _session_id: str):
        return SimpleNamespace(agent="build")

    async def fake_session_update(cls, _session_id: str, **_kwargs):
        return SimpleNamespace(agent="build")

    async def fake_agent_get(cls, _name: str):
        return SimpleNamespace(mode="primary")

    async def fake_default_agent(cls):
        return "build"

    async def fake_system_prompt(cls, **_kwargs):
        return "system prompt"

    async def fake_prompt(cls, **kwargs):
        on_reasoning_start = kwargs.get("on_reasoning_start")
        on_reasoning_delta = kwargs.get("on_reasoning_delta")
        on_reasoning_end = kwargs.get("on_reasoning_end")
        on_step_start = kwargs.get("on_step_start")
        on_step_finish = kwargs.get("on_step_finish")
        on_patch = kwargs.get("on_patch")

        assert on_reasoning_start is not None
        assert on_reasoning_delta is not None
        assert on_reasoning_end is not None
        assert on_step_start is not None
        assert on_step_finish is not None
        assert on_patch is not None

        def _maybe_await(result):
            if inspect.isawaitable(result):
                return result
            return None

        _maybe_await(on_step_start("snap_start"))
        maybe = _maybe_await(on_reasoning_start("r1", {"provider": "openai"}))
        if maybe:
            await maybe
        maybe = _maybe_await(on_reasoning_delta("r1", "plan ", {"provider": "openai"}))
        if maybe:
            await maybe
        maybe = _maybe_await(on_reasoning_delta("r1", "done", {"provider": "openai"}))
        if maybe:
            await maybe
        maybe = _maybe_await(on_reasoning_end("r1", {"provider": "openai"}))
        if maybe:
            await maybe
        _maybe_await(on_step_finish("stop", "snap_end", {"input": 3, "output": 5, "reasoning": 7}, 0.12))
        _maybe_await(on_patch("patch-hash", ["src/hotaru/tui/context/sdk.py"]))

        return SimpleNamespace(result=SimpleNamespace(error=None, usage={"input_tokens": 1}))

    monkeypatch.setattr(SDKContext, "_ensure_project", fake_ensure_project)
    monkeypatch.setattr("hotaru.provider.provider.Provider.get_model", classmethod(fake_get_model))
    monkeypatch.setattr("hotaru.provider.provider.Provider.default_model", classmethod(fake_default_model))
    monkeypatch.setattr("hotaru.session.session.Session.get", classmethod(fake_session_get))
    monkeypatch.setattr("hotaru.session.session.Session.update", classmethod(fake_session_update))
    monkeypatch.setattr("hotaru.agent.agent.Agent.get", classmethod(fake_agent_get))
    monkeypatch.setattr("hotaru.agent.agent.Agent.default_agent", classmethod(fake_default_agent))
    monkeypatch.setattr("hotaru.session.system.SystemPrompt.build_full_prompt", classmethod(fake_system_prompt))
    monkeypatch.setattr("hotaru.session.prompting.SessionPrompt.prompt", classmethod(fake_prompt))

    events = []
    async for event in sdk.send_message(
        session_id="session_1",
        content="hello",
        agent="build",
        model="openai/gpt-5",
    ):
        events.append(event)

    part_updates = [
        event.get("data", {}).get("part", {})
        for event in events
        if event.get("type") == "message.part.updated"
    ]
    part_types = [part.get("type") for part in part_updates]

    assert "reasoning" in part_types
    assert "step-start" in part_types
    assert "step-finish" in part_types
    assert "patch" in part_types

    reasoning_part = [part for part in part_updates if part.get("type") == "reasoning"][-1]
    assert reasoning_part.get("text") == "plan done"

    step_finish_part = next(part for part in part_updates if part.get("type") == "step-finish")
    assert step_finish_part.get("reason") == "stop"

    patch_part = next(part for part in part_updates if part.get("type") == "patch")
    assert patch_part.get("files") == ["src/hotaru/tui/context/sdk.py"]
