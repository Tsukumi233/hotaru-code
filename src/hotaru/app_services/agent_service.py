"""Agent application service."""

from __future__ import annotations

from typing import Any

from ..agent import Agent


class AgentService:
    """Thin orchestration for agent operations."""

    @classmethod
    async def list(cls) -> list[dict[str, Any]]:
        agents = await Agent.list()
        return [
            {
                "name": agent.name,
                "description": agent.description,
                "mode": agent.mode,
                "hidden": agent.hidden,
            }
            for agent in agents
        ]
