"""Permission transport routes."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends

from ...app_services import PermissionService
from ...runtime import AppContext
from ..deps import resolve_app_context
from ..schemas import PermissionReplyRequest

router = APIRouter(prefix="/v1/permissions", tags=["permissions"])


@router.get("")
async def list_permissions(ctx: AppContext = Depends(resolve_app_context)) -> list[dict[str, object]]:
    return await PermissionService.list(ctx)


@router.post("/{request_id}/reply")
async def reply_permission(
    request_id: str,
    payload: PermissionReplyRequest = Body(...),
    ctx: AppContext = Depends(resolve_app_context),
) -> bool:
    return await PermissionService.reply(ctx, request_id, payload.model_dump(exclude_none=True))
