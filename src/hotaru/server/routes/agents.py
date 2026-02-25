"""Agent transport routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...app_services import AgentService
from ...runtime import AppContext
from ..deps import resolve_app_context
from ..schemas import AgentResponse

router = APIRouter(prefix="/v1/agents", tags=["agents"])


@router.get("", response_model=list[AgentResponse])
async def list_agents(app: AppContext = Depends(resolve_app_context)) -> list[dict[str, object]]:
    return await AgentService.list(app=app)
