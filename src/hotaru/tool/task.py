"""Task tool for launching subagents."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from ..agent import Agent, AgentMode
from ..permission import Permission, PermissionAction
from ..util.log import Log
from .tool import PermissionSpec, Tool, ToolContext, ToolResult

log = Log.create({"service": "tool.task"})

_DESCRIPTION_TEMPLATE_PATH = Path(__file__).parent / "task.txt"
_DESCRIPTION_TEMPLATE = _DESCRIPTION_TEMPLATE_PATH.read_text(encoding="utf-8")
_SUBAGENT_MENTION_RE = re.compile(r"^\s*@([A-Za-z0-9._-]+)\s+(.+)$", re.DOTALL)


class TaskParams(BaseModel):
    """Parameters for task tool calls."""

    description: str = Field(..., description="A short description of the delegated task")
    prompt: str = Field(..., description="The detailed task prompt for the subagent")
    subagent_type: str = Field(..., description="The subagent name to invoke")
    task_id: Optional[str] = Field(None, description="Optional existing task session ID to resume")
    command: Optional[str] = Field(None, description="Optional command that triggered this task")


def extract_subagent_mention(text: str) -> Optional[tuple[str, str]]:
    """Parse a leading ``@subagent`` mention."""
    match = _SUBAGENT_MENTION_RE.match(text.strip())
    if not match:
        return None
    return match.group(1), match.group(2).strip()


def short_description(prompt: str) -> str:
    """Create a short description from prompt text."""
    words = [w for w in re.split(r"\s+", prompt.strip()) if w]
    if not words:
        return "subtask"
    return " ".join(words[:5])


async def build_task_description(caller_agent: Optional[str] = None) -> str:
    """Build dynamic task tool description with accessible subagents."""
    agents = [agent for agent in await Agent.list() if agent.mode != AgentMode.PRIMARY]

    caller = await Agent.get(caller_agent) if caller_agent else None
    if caller:
        caller_ruleset = Permission.from_config_list(caller.permission)
        filtered = []
        for agent in agents:
            decision = Permission.evaluate("task", agent.name, caller_ruleset)
            if decision.action != PermissionAction.DENY:
                filtered.append(agent)
        agents = filtered

    if not agents:
        listing = "- (no subagents available)"
    else:
        lines = []
        for agent in agents:
            desc = agent.description or "Specialized assistant."
            lines.append(f"- {agent.name}: {desc}")
        listing = "\n".join(lines)

    return _DESCRIPTION_TEMPLATE.replace("{agents}", listing)


async def _resolve_task_model(
    *,
    agent_name: str,
    parent_session: Any,
    context: ToolContext,
) -> tuple[str, str]:
    from ..provider import Provider

    agent = await Agent.get(agent_name)
    if agent and agent.model:
        return agent.model.provider_id, agent.model.model_id

    if parent_session and parent_session.provider_id and parent_session.model_id:
        return parent_session.provider_id, parent_session.model_id

    provider_id = str(context.extra.get("provider_id") or "")
    model_id = str(context.extra.get("model_id") or "")
    if provider_id and model_id:
        return provider_id, model_id

    return await Provider.default_model()


async def _run_subagent_task(params: TaskParams, ctx: ToolContext) -> ToolResult:
    from ..project import Project
    from ..provider import Provider
    from ..session.prompting import SessionPrompt
    from ..session.session import Session
    from ..session.system import SystemPrompt

    agent = await Agent.get(params.subagent_type)
    if not agent:
        raise ValueError(f"Unknown subagent type: {params.subagent_type}")
    if agent.mode == AgentMode.PRIMARY:
        raise ValueError(f"Agent '{params.subagent_type}' is primary and cannot be launched as a task")

    parent_session = await Session.get(ctx.session_id)
    if not parent_session:
        raise ValueError(f"Parent session not found: {ctx.session_id}")

    cwd = str(ctx.extra.get("cwd") or Path.cwd())
    worktree = str(ctx.extra.get("worktree") or cwd)
    provider_id, model_id = await _resolve_task_model(agent_name=agent.name, parent_session=parent_session, context=ctx)
    model_info = await Provider.get_model(provider_id, model_id)

    session = None
    if params.task_id:
        session = await Session.get(params.task_id)

    if not session:
        session = await Session.create(
            project_id=parent_session.project_id,
            agent=agent.name,
            directory=cwd,
            model_id=model_id,
            provider_id=provider_id,
            parent_id=ctx.session_id,
        )
        await Session.update(session.id, project_id=session.project_id, title=f"{params.description} (@{agent.name} subagent)")

    project, _ = await Project.from_directory(cwd)
    system_prompt = await SystemPrompt.build_full_prompt(
        model=model_info,
        directory=cwd,
        worktree=worktree,
        is_git=project.vcs == "git",
    )

    prompt_result = await SessionPrompt.prompt(
        session_id=session.id,
        content=params.prompt,
        provider_id=provider_id,
        model_id=model_id,
        agent=agent.name,
        cwd=cwd,
        worktree=worktree,
        system_prompt=system_prompt,
        resume_history=bool(params.task_id),
    )
    result = prompt_result.result

    if result.error:
        raise RuntimeError(result.error)

    output = "\n".join(
        [
            f"task_id: {session.id} (use this task_id to continue this subagent session)",
            "",
            "<task_result>",
            result.text.strip(),
            "</task_result>",
        ]
    )

    return ToolResult(
        title=params.description,
        output=output,
        metadata={
            "session_id": session.id,
            "model": {
                "provider_id": provider_id,
                "model_id": model_id,
            },
        },
    )


def task_permissions(params: TaskParams, ctx: ToolContext) -> list[PermissionSpec]:
    if bool(ctx.extra.get("bypass_agent_check")):
        return []
    return [
        PermissionSpec(
            permission="task",
            patterns=[params.subagent_type],
            always=["*"],
            metadata={
                "description": params.description,
                "subagent_type": params.subagent_type,
            },
        )
    ]


TaskTool = Tool.define(
    tool_id="task",
    description="Delegate a task to a specialized subagent.",
    parameters_type=TaskParams,
    permission_fn=task_permissions,
    execute_fn=_run_subagent_task,
    auto_truncate=False,
)
