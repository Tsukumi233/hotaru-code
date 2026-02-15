from pathlib import Path

import pytest

from hotaru.agent.agent import AgentInfo, AgentMode
from hotaru.permission import Permission
from hotaru.session.llm import LLM, StreamChunk
from hotaru.session.processor import SessionProcessor
from hotaru.skill.skill import Skill, SkillInfo
from hotaru.tool.skill import SkillParams, build_skill_description, skill_execute
from hotaru.tool.tool import ToolContext


@pytest.mark.anyio
async def test_skill_description_hides_denied_skills(monkeypatch: pytest.MonkeyPatch) -> None:
    skills = [
        SkillInfo(
            name="public-skill",
            description="Public",
            location="/tmp/public/SKILL.md",
            content="# Public",
            directory="/tmp/public",
        ),
        SkillInfo(
            name="internal-docs",
            description="Internal",
            location="/tmp/internal/SKILL.md",
            content="# Internal",
            directory="/tmp/internal",
        ),
    ]

    async def fake_list(cls):
        return skills

    async def fake_get_agent(cls, name: str):
        return AgentInfo(
            name=name,
            mode=AgentMode.PRIMARY,
            permission=[{"permission": "skill", "pattern": "internal-*", "action": "deny"}],
            options={},
        )

    monkeypatch.setattr(Skill, "list", classmethod(fake_list))
    monkeypatch.setattr("hotaru.agent.agent.Agent.get", classmethod(fake_get_agent))

    description = await build_skill_description("build")
    assert "<name>public-skill</name>" in description
    assert "<name>internal-docs</name>" not in description


@pytest.mark.anyio
async def test_skill_execute_returns_content_and_requests_permission(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    skill_dir = tmp_path / "tool-skill"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "scripts").mkdir(parents=True, exist_ok=True)
    (skill_dir / "scripts" / "demo.txt").write_text("demo", encoding="utf-8")

    info = SkillInfo(
        name="tool-skill",
        description="Skill for tool tests",
        location=str((skill_dir / "SKILL.md").resolve()),
        content="# Tool Skill\n\nUse this skill.",
        directory=str(skill_dir.resolve()),
    )

    async def fake_get(cls, name: str):
        return info if name == "tool-skill" else None

    async def fake_names(cls):
        return ["tool-skill"]

    captured = {}

    async def fake_permission_ask(
        cls,
        session_id: str,
        permission: str,
        patterns: list[str],
        ruleset,
        always=None,
        metadata=None,
        request_id=None,
        tool=None,
    ):
        captured["session_id"] = session_id
        captured["permission"] = permission
        captured["patterns"] = patterns
        captured["always"] = always
        captured["metadata"] = metadata

    monkeypatch.setattr(Skill, "get", classmethod(fake_get))
    monkeypatch.setattr(Skill, "names", classmethod(fake_names))
    monkeypatch.setattr(Permission, "ask", classmethod(fake_permission_ask))

    ctx = ToolContext(
        session_id="session-1",
        message_id="message-1",
        agent="build",
    )
    result = await skill_execute(SkillParams(name="tool-skill"), ctx)

    assert captured["permission"] == "skill"
    assert captured["patterns"] == ["tool-skill"]
    assert captured["always"] == ["tool-skill"]
    assert result.metadata["dir"] == str(skill_dir.resolve())
    assert result.output.startswith('<skill_content name="tool-skill">')
    assert "<skill_files>" in result.output
    assert str((skill_dir / "scripts" / "demo.txt").resolve()) in result.output


@pytest.mark.anyio
async def test_session_filters_out_skill_tool_when_permission_denied(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured = {}

    async def fake_stream(cls, stream_input):
        captured["tools"] = stream_input.tools
        yield StreamChunk(type="text", text="done")

    async def fake_get_agent(cls, name: str):
        return AgentInfo(
            name=name,
            mode=AgentMode.PRIMARY,
            permission=[{"permission": "skill", "pattern": "*", "action": "deny"}],
            options={},
        )

    monkeypatch.setattr(LLM, "stream", classmethod(fake_stream))
    monkeypatch.setattr("hotaru.agent.agent.Agent.get", classmethod(fake_get_agent))

    processor = SessionProcessor(
        session_id="ses_skill_disable",
        model_id="model",
        provider_id="provider",
        agent="build",
        cwd=str(tmp_path),
        worktree=str(tmp_path),
    )

    result = await processor.process(user_message="hello")
    assert result.status == "stop"

    tool_names = {item["function"]["name"] for item in (captured["tools"] or [])}
    assert "skill" not in tool_names
