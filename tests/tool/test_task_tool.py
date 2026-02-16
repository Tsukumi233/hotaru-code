import pytest

from hotaru.agent.agent import AgentInfo, AgentMode
from hotaru.core.global_paths import GlobalPath
from hotaru.provider.provider import ProcessedModelInfo
from hotaru.session.session import Session
from hotaru.storage import Storage
from hotaru.tool.task import build_task_description, extract_subagent_mention
from hotaru.tool.task import TaskParams, _run_subagent_task
from hotaru.tool.tool import ToolContext


@pytest.mark.anyio
async def test_task_description_respects_task_permission_rules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    general = AgentInfo(
        name="general",
        description="General subagent",
        mode=AgentMode.SUBAGENT,
        permission=[],
        options={},
    )
    explore = AgentInfo(
        name="explore",
        description="Explore subagent",
        mode=AgentMode.SUBAGENT,
        permission=[],
        options={},
    )
    caller = AgentInfo(
        name="build",
        mode=AgentMode.PRIMARY,
        permission=[
            {"permission": "task", "pattern": "*", "action": "deny"},
            {"permission": "task", "pattern": "general", "action": "allow"},
        ],
        options={},
    )

    async def fake_list(cls):
        return [general, explore]

    async def fake_get(cls, name: str):
        if name == "build":
            return caller
        return None

    monkeypatch.setattr("hotaru.agent.agent.Agent.list", classmethod(fake_list))
    monkeypatch.setattr("hotaru.agent.agent.Agent.get", classmethod(fake_get))

    description = await build_task_description(caller_agent="build")

    assert "- general:" in description
    assert "- explore:" not in description
    assert "When NOT to use the Task tool:" in description
    assert "should be used proactively" in description


def test_extract_subagent_mention() -> None:
    assert extract_subagent_mention("@general investigate auth flow") == ("general", "investigate auth flow")
    assert extract_subagent_mention("please @general investigate") is None


@pytest.mark.anyio
async def test_task_tool_reuses_existing_task_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(GlobalPath, "data", classmethod(lambda cls: str(data_dir)))
    Storage.reset()

    parent = await Session.create(
        project_id="p1",
        agent="build",
        directory=str(tmp_path),
        provider_id="openai",
        model_id="gpt-5",
    )
    existing = await Session.create(
        project_id="p1",
        agent="explore",
        directory=str(tmp_path),
        provider_id="openai",
        model_id="gpt-5",
        parent_id=parent.id,
    )

    async def fake_get_agent(cls, name: str):
        if name == "explore":
            return AgentInfo(name="explore", mode=AgentMode.SUBAGENT, permission=[], options={})
        if name == "build":
            return AgentInfo(name="build", mode=AgentMode.PRIMARY, permission=[], options={})
        return None

    async def fake_get_model(cls, provider_id: str, model_id: str):
        return ProcessedModelInfo(id=model_id, provider_id=provider_id, name=model_id, api_id=model_id)

    class _DummyProject:
        vcs = "git"

    async def fake_from_directory(_directory: str):
        return _DummyProject(), str(tmp_path)

    async def fake_build_full_prompt(cls, **_kwargs):
        return "sys"

    captured = {}

    async def fake_prompt(cls, **kwargs):
        captured.update(kwargs)
        from hotaru.session.processor import ProcessorResult
        from hotaru.session.prompting import PromptResult

        return PromptResult(
            result=ProcessorResult(status="stop", text="resumed"),
            assistant_message_id="message_assistant",
            user_message_id="message_user",
            text="resumed",
        )

    monkeypatch.setattr("hotaru.agent.agent.Agent.get", classmethod(fake_get_agent))
    monkeypatch.setattr("hotaru.provider.provider.Provider.get_model", classmethod(fake_get_model))
    monkeypatch.setattr("hotaru.project.project.Project.from_directory", staticmethod(fake_from_directory))
    monkeypatch.setattr("hotaru.session.system.SystemPrompt.build_full_prompt", classmethod(fake_build_full_prompt))
    monkeypatch.setattr("hotaru.session.prompting.SessionPrompt.prompt", classmethod(fake_prompt))

    result = await _run_subagent_task(
        TaskParams(
            description="resume task",
            prompt="continue",
            subagent_type="explore",
            task_id=existing.id,
        ),
        ToolContext(
            session_id=parent.id,
            message_id="message_parent",
            agent="build",
            call_id="call_1",
            extra={"cwd": str(tmp_path), "worktree": str(tmp_path), "bypass_agent_check": True},
        ),
    )

    assert result.metadata["session_id"] == existing.id
    assert captured["session_id"] == existing.id
    assert captured["resume_history"] is True
