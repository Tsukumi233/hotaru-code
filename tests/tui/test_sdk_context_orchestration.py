from types import SimpleNamespace

import pytest

from hotaru.provider.provider import ProcessedModelInfo
from hotaru.tui.context.sdk import SDKContext


@pytest.mark.anyio
async def test_send_message_uses_shared_prompt_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    sdk = SDKContext(cwd=str(tmp_path))
    calls: list[dict] = []

    async def fake_prepare_send_message_context(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            provider_id="openai",
            model_id="gpt-5",
            model_info=ProcessedModelInfo(
                id="gpt-5",
                provider_id="openai",
                name="gpt-5",
                api_id="gpt-5",
            ),
            session=SimpleNamespace(id="session_1", agent="build"),
            agent_name="build",
            system_prompt="system prompt",
        )

    async def fake_ensure_project(self):
        self._project = SimpleNamespace(vcs="git", id="project_1")
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
        return SimpleNamespace(id="session_1", agent="build")

    async def fake_session_update(cls, _session_id: str, **_kwargs):
        return SimpleNamespace(id="session_1", agent="build")

    async def fake_agent_get(cls, _name: str):
        return SimpleNamespace(mode="primary")

    async def fake_default_agent(cls):
        return "build"

    async def fake_system_prompt(cls, **_kwargs):
        return "system prompt"

    async def fake_prompt(cls, **kwargs):
        on_text = kwargs.get("on_text")
        if on_text:
            on_text("ok")
        return SimpleNamespace(result=SimpleNamespace(error=None, usage={"input_tokens": 1}))

    monkeypatch.setattr("hotaru.tui.context.sdk.prepare_send_message_context", fake_prepare_send_message_context, raising=False)
    monkeypatch.setattr(SDKContext, "_ensure_project", fake_ensure_project)
    monkeypatch.setattr("hotaru.provider.provider.Provider.get_model", classmethod(fake_get_model))
    monkeypatch.setattr("hotaru.provider.provider.Provider.default_model", classmethod(fake_default_model))
    monkeypatch.setattr("hotaru.session.session.Session.get", classmethod(fake_session_get))
    monkeypatch.setattr("hotaru.session.session.Session.update", classmethod(fake_session_update))
    monkeypatch.setattr("hotaru.agent.agent.Agent.get", classmethod(fake_agent_get))
    monkeypatch.setattr("hotaru.agent.agent.Agent.default_agent", classmethod(fake_default_agent))
    monkeypatch.setattr("hotaru.session.system.SystemPrompt.build_full_prompt", classmethod(fake_system_prompt))
    monkeypatch.setattr("hotaru.session.prompting.SessionPrompt.prompt", classmethod(fake_prompt))

    async for _event in sdk.send_message(
        session_id="session_1",
        content="hello",
        agent="build",
        model="openai/gpt-5",
    ):
        pass

    assert len(calls) == 1
