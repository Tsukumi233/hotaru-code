from types import SimpleNamespace

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
