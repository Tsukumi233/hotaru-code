"""Agent transport routes."""

from __future__ import annotations

from ...app_services import AgentService
from ..schemas import AgentResponse
from .crud import crud_router, many


async def list_agents() -> list[dict[str, object]]:
    return await AgentService.list()


router = crud_router(
    prefix="/v1/agents",
    tags=["agents"],
    routes=[
        many("GET", "", AgentResponse, list_agents),
    ],
)
