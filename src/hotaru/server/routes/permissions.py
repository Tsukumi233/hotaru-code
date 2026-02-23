"""Permission transport routes."""

from __future__ import annotations

from fastapi import Body, Depends

from ...app_services import PermissionService
from ...runtime import AppContext
from ..deps import resolve_app_context
from ..schemas import PermissionReplyRequest
from .crud import crud_router, raw


async def list_permissions(ctx: AppContext = Depends(resolve_app_context)) -> list[dict[str, object]]:
    return await PermissionService.list(ctx)


async def reply_permission(
    request_id: str,
    payload: PermissionReplyRequest = Body(...),
    ctx: AppContext = Depends(resolve_app_context),
) -> bool:
    return await PermissionService.reply(ctx, request_id, payload.model_dump(exclude_none=True))


router = crud_router(
    prefix="/v1/permissions",
    tags=["permissions"],
    routes=[
        raw("GET", "", list[dict[str, object]], list_permissions),
        raw("POST", "/{request_id}/reply", bool, reply_permission),
    ],
)
