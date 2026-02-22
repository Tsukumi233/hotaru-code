"""Agent transport routes."""

from __future__ import annotations

from fastapi import APIRouter

from ...app_services import AgentService
from ..schemas import AgentResponse

router = APIRouter(prefix="/v1/agents", tags=["agents"])


@router.get("", response_model=list[AgentResponse])
async def list_agents() -> list[AgentResponse]:
    result = await AgentService.list()
    return [AgentResponse.model_validate(item) for item in result]
