"""Agent application service."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..runtime import AppContext


class AgentService:
    """Thin orchestration for agent operations."""

    @classmethod
    async def list(cls, *, app: AppContext) -> list[dict[str, Any]]:
        agents = await app.agents.list()
        return [
            {
                "name": agent.name,
                "description": str(agent.description or ""),
                "mode": agent.mode,
                "hidden": agent.hidden,
            }
            for agent in agents
        ]
