"""Agent transport routes."""

from __future__ import annotations

from fastapi import Depends

from ...app_services import AgentService
from ...runtime import AppContext
from ..deps import resolve_app_context
from ..schemas import AgentResponse
from .crud import crud_router, many


async def list_agents(app: AppContext = Depends(resolve_app_context)) -> list[dict[str, object]]:
    return await AgentService.list(app=app)


router = crud_router(
    prefix="/v1/agents",
    tags=["agents"],
    routes=[
        many("GET", "", AgentResponse, list_agents),
    ],
)
