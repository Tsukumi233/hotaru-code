"""Application runtime service container."""

from __future__ import annotations

from typing import Optional

from ..agent.agent import Agent
from ..core.bus import Bus
from ..lsp import LSP
from ..mcp import MCP
from ..permission import Permission
from ..question import Question
from ..skill import Skill
from ..tool.registry import ToolRegistry
from .runner import SessionRuntime


async def _resolve_project(session_id: str) -> Optional[str]:
    from ..session.session import Session

    session = await Session.get(session_id)
    if session:
        return session.project_id
    return None


async def _resolve_scope() -> str:
    from ..core.config import ConfigManager

    config = await ConfigManager.get()
    configured = config.permission_memory_scope
    if configured:
        candidate = str(configured)
        if candidate in {"turn", "session", "project", "persisted"}:
            return candidate
    return "session"


class AppRuntime:
    """Container for process-level service instances."""

    __slots__ = (
        "bus",
        "agents",
        "tools",
        "permission",
        "question",
        "skills",
        "mcp",
        "lsp",
        "runner",
    )

    def __init__(self) -> None:
        self.bus = Bus()
        self.permission = Permission(
            project_resolver=_resolve_project,
            scope_resolver=_resolve_scope,
        )
        self.question = Question()
        self.skills = Skill()
        self.agents = Agent(self.skills)
        self.tools = ToolRegistry()
        self.mcp = MCP()
        self.lsp = LSP()
        self.runner = SessionRuntime(self.clear_session)

    async def clear_session(self, session_id: str) -> None:
        await self.permission.clear_session(session_id)
        await self.question.clear_session(session_id)

