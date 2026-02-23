from types import SimpleNamespace

import pytest

from hotaru.cli.cmd.run import run_command
from hotaru.provider.provider import ProcessedModelInfo
from tests.helpers import fake_app


def _fake_runtime():
    return fake_app()


@pytest.mark.anyio
async def test_run_command_uses_shared_prompt_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    calls: list[dict] = []

    async def fake_prepare_prompt_context(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            project=SimpleNamespace(id="project_1", vcs="git"),
            sandbox=str(tmp_path),
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
            is_resuming=False,
            warnings=[],
        )

    async def fake_project_from_directory(cls, _cwd: str):
        return SimpleNamespace(id="project_1", vcs="git"), str(tmp_path)

    async def fake_prompt(cls, **kwargs):
        on_text = kwargs.get("on_text")
        if on_text:
            on_text("ok")
        return SimpleNamespace(
            assistant_message_id="message_1",
            result=SimpleNamespace(error=None, usage={"input_tokens": 1, "output_tokens": 1}),
        )

    monkeypatch.setattr("hotaru.cli.cmd.run.prepare_prompt_context", fake_prepare_prompt_context, raising=False)
    monkeypatch.setattr("hotaru.cli.cmd.run.Project.from_directory", classmethod(fake_project_from_directory))
    monkeypatch.setattr("hotaru.cli.cmd.run.SessionPrompt.prompt", classmethod(fake_prompt))
    monkeypatch.setattr("hotaru.cli.cmd.run.Bus.subscribe", lambda *_args, **_kwargs: (lambda: None))
    monkeypatch.setattr("hotaru.cli.cmd.run.AppContext", _fake_runtime)

    await run_command(message="hello", json_output=True, show_thinking=False)

    assert len(calls) == 1
