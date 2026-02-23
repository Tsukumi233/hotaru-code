"""Shared prompt-orchestration helpers for interface layers.

This module centralizes model/agent/session/system-prompt preparation so
CLI/TUI layers don't duplicate workflow logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

from ..provider import Provider
from ..provider.provider import ProcessedModelInfo
from .session import Session
from .system import SystemPrompt

if TYPE_CHECKING:
    from ..agent.agent import Agent
    from ..runtime import AppContext


@dataclass
class PromptContext:
    """Resolved prompt execution context."""

    provider_id: str
    model_id: str
    model_info: ProcessedModelInfo
    session: Any
    agent_name: str
    system_prompt: str
    is_resuming: bool = False
    warnings: list[str] = field(default_factory=list)


async def prepare_prompt_context(
    *,
    app: AppContext,
    cwd: str,
    sandbox: str,
    project_id: str,
    project_vcs: Optional[str],
    model: Optional[str],
    requested_agent: Optional[str],
    session_id: Optional[str],
    continue_session: bool,
) -> PromptContext:
    """Prepare context for one-shot run-style prompt execution."""

    provider_id, model_id, model_info = await _resolve_model(model=model)
    validated_agent, warnings = await _validate_requested_agent(app.agents, requested_agent)

    if continue_session:
        sessions = await Session.list(project_id)
        if sessions:
            session = sessions[0]
        else:
            initial_agent = validated_agent or await app.agents.default_agent()
            session = await Session.create(
                project_id=project_id,
                agent=initial_agent,
                directory=cwd,
                model_id=model_id,
                provider_id=provider_id,
            )
    elif session_id:
        session = await Session.get(session_id)
        if not session:
            raise ValueError(f"Session '{session_id}' not found")
    else:
        initial_agent = validated_agent or await app.agents.default_agent()
        session = await Session.create(
            project_id=project_id,
            agent=initial_agent,
            directory=cwd,
            model_id=model_id,
            provider_id=provider_id,
        )

    agent_name = validated_agent or session.agent or await app.agents.default_agent()
    if agent_name != session.agent:
        updated = await Session.update(session.id, agent=agent_name)
        if updated:
            session = updated

    system_prompt = await SystemPrompt.build_full_prompt(
        model=model_info,
        directory=cwd,
        worktree=sandbox,
        is_git=project_vcs == "git",
    )

    return PromptContext(
        provider_id=provider_id,
        model_id=model_id,
        model_info=model_info,
        session=session,
        agent_name=agent_name,
        system_prompt=system_prompt,
        is_resuming=continue_session or (session_id is not None),
        warnings=warnings,
    )


async def prepare_send_message_context(
    *,
    app: AppContext,
    cwd: str,
    sandbox: str,
    project_vcs: Optional[str],
    session_id: str,
    model: Optional[str],
    requested_agent: Optional[str],
) -> PromptContext:
    """Prepare context for SDK/TUI send_message execution."""

    provider_id, model_id, model_info = await _resolve_model(model=model)

    session = await Session.get(session_id)
    agent_name = requested_agent or (session.agent if session else None)
    if agent_name:
        agent_info = await app.agents.get(agent_name)
        if not agent_info or agent_info.mode == "subagent":
            agent_name = await app.agents.default_agent()
    else:
        agent_name = await app.agents.default_agent()

    if session and session.agent != agent_name:
        updated = await Session.update(session_id, agent=agent_name)
        if updated:
            session = updated

    system_prompt = await SystemPrompt.build_full_prompt(
        model=model_info,
        directory=cwd,
        worktree=sandbox,
        is_git=project_vcs == "git",
    )

    return PromptContext(
        provider_id=provider_id,
        model_id=model_id,
        model_info=model_info,
        session=session,
        agent_name=agent_name,
        system_prompt=system_prompt,
    )


async def _resolve_model(*, model: Optional[str]) -> tuple[str, str, ProcessedModelInfo]:
    if model:
        provider_id, model_id = Provider.parse_model(model)
    else:
        provider_id, model_id = await Provider.default_model()

    model_info = await Provider.get_model(provider_id, model_id)
    return provider_id, model_id, model_info


async def _validate_requested_agent(agents: Agent, requested_agent: Optional[str]) -> tuple[Optional[str], list[str]]:
    if not requested_agent:
        return None, []

    agent_info = await agents.get(requested_agent)
    if not agent_info:
        return None, [f"Agent '{requested_agent}' not found, using session/default"]
    if agent_info.mode == "subagent":
        return None, [f"Agent '{requested_agent}' is a subagent, using session/default"]
    return requested_agent, []
