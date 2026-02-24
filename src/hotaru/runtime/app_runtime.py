"""Application runtime service container."""

from __future__ import annotations

from ..agent.agent import Agent
from ..core.bus import Bus
from ..lsp import LSP
from ..mcp import MCP
from ..permission import Permission
from ..question import Question
from ..skill import Skill
from ..tool.registry import ToolRegistry
from .runner import SessionRuntime


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
        self.permission = Permission()
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

