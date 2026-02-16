import inspect
import json
from types import SimpleNamespace

import pytest

from hotaru.provider.provider import ProcessedModelInfo
from hotaru.cli.cmd.run import run_command


@pytest.mark.anyio
async def test_run_command_json_emits_reasoning_and_tool_use_in_part_order(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path,
) -> None:
    async def fake_project_from_directory(cls, _cwd: str):
        return SimpleNamespace(id="project_1", vcs="git"), str(tmp_path)

    async def fake_default_model(cls):
        return ("openai", "gpt-5")

    async def fake_get_model(cls, provider_id: str, model_id: str):
        return ProcessedModelInfo(
            id=model_id,
            provider_id=provider_id,
            name=model_id,
            api_id=model_id,
        )

    async def fake_default_agent(cls):
        return "build"

    async def fake_session_create(cls, **_kwargs):
        return SimpleNamespace(id="session_1", agent="build")

    async def fake_session_update(cls, _session_id: str, **_kwargs):
        return SimpleNamespace(id="session_1", agent="build")

    async def fake_system_prompt(cls, **_kwargs):
        return "system prompt"

    async def fake_prompt(cls, **kwargs):
        on_text = kwargs.get("on_text")
        on_tool_update = kwargs.get("on_tool_update")
        on_reasoning_start = kwargs.get("on_reasoning_start")
        on_reasoning_delta = kwargs.get("on_reasoning_delta")
        on_reasoning_end = kwargs.get("on_reasoning_end")

        assert on_text is not None
        assert on_tool_update is not None
        assert on_reasoning_start is not None
        assert on_reasoning_delta is not None
        assert on_reasoning_end is not None

        def _maybe_await(result):
            if inspect.isawaitable(result):
                return result
            return None

        maybe = _maybe_await(on_reasoning_start(None, {"provider": "openai"}))
        if maybe:
            await maybe
        maybe = _maybe_await(on_reasoning_delta(None, "first", {"provider": "openai"}))
        if maybe:
            await maybe
        maybe = _maybe_await(on_reasoning_end(None, {"provider": "openai"}))
        if maybe:
            await maybe

        on_tool_update(
            {
                "id": "call_tool_1",
                "name": "read",
                "input_json": '{"filePath":"README.md"}',
                "input": {"filePath": "README.md"},
                "status": "running",
                "output": "",
                "error": None,
                "title": "Read file",
                "metadata": {},
                "attachments": [],
                "start_time": 10,
                "end_time": None,
            }
        )
        on_tool_update(
            {
                "id": "call_tool_1",
                "name": "read",
                "input_json": '{"filePath":"README.md"}',
                "input": {"filePath": "README.md"},
                "status": "completed",
                "output": "ok",
                "error": None,
                "title": "Read file",
                "metadata": {},
                "attachments": [],
                "start_time": 10,
                "end_time": 11,
            }
        )

        maybe = _maybe_await(on_reasoning_start(None, {"provider": "openai"}))
        if maybe:
            await maybe
        maybe = _maybe_await(on_reasoning_delta(None, "second", {"provider": "openai"}))
        if maybe:
            await maybe
        maybe = _maybe_await(on_reasoning_end(None, {"provider": "openai"}))
        if maybe:
            await maybe

        on_text("final answer")

        return SimpleNamespace(
            assistant_message_id="message_1",
            result=SimpleNamespace(
                error=None,
                usage={"input_tokens": 1, "output_tokens": 2},
            ),
        )

    monkeypatch.setattr("hotaru.cli.cmd.run.Project.from_directory", classmethod(fake_project_from_directory))
    monkeypatch.setattr("hotaru.cli.cmd.run.Provider.default_model", classmethod(fake_default_model))
    monkeypatch.setattr("hotaru.cli.cmd.run.Provider.get_model", classmethod(fake_get_model))
    monkeypatch.setattr("hotaru.cli.cmd.run.Agent.default_agent", classmethod(fake_default_agent))
    monkeypatch.setattr("hotaru.cli.cmd.run.Session.create", classmethod(fake_session_create))
    monkeypatch.setattr("hotaru.cli.cmd.run.Session.update", classmethod(fake_session_update))
    monkeypatch.setattr("hotaru.cli.cmd.run.SystemPrompt.build_full_prompt", classmethod(fake_system_prompt))
    monkeypatch.setattr("hotaru.cli.cmd.run.SessionPrompt.prompt", classmethod(fake_prompt))
    monkeypatch.setattr("hotaru.cli.cmd.run.Bus.subscribe", lambda *_args, **_kwargs: (lambda: None))

    await run_command(
        message="hello",
        json_output=True,
        show_thinking=True,
    )

    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    events = [json.loads(line) for line in lines]
    core_types = [event["type"] for event in events if event.get("type") in {"reasoning", "tool_use", "text"}]
    assert core_types == ["reasoning", "tool_use", "reasoning", "text"]
