import pytest

from hotaru.agent.agent import AgentInfo, AgentMode
from hotaru.tool.task import build_task_description, extract_subagent_mention


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


def test_extract_subagent_mention() -> None:
    assert extract_subagent_mention("@general investigate auth flow") == ("general", "investigate auth flow")
    assert extract_subagent_mention("please @general investigate") is None
