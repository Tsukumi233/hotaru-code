"""Permission transport routes."""

from __future__ import annotations

from fastapi import APIRouter, Body

from ...app_services import PermissionService
from ..schemas import PermissionReplyRequest

router = APIRouter(prefix="/v1/permissions", tags=["permissions"])


@router.get("", response_model=list[dict[str, object]])
async def list_permissions() -> list[dict[str, object]]:
    result = await PermissionService.list()
    return [dict(item) for item in result]


@router.post("/{request_id}/reply", response_model=bool)
async def reply_permission(request_id: str, payload: PermissionReplyRequest = Body(...)) -> bool:
    return await PermissionService.reply(request_id, payload.model_dump(exclude_none=True))
