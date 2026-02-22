"""Permission transport routes."""

from __future__ import annotations

from fastapi import Body

from ...app_services import PermissionService
from ..schemas import PermissionReplyRequest
from .crud import crud_router, raw

async def list_permissions() -> list[dict[str, object]]:
    return await PermissionService.list()


async def reply_permission(request_id: str, payload: PermissionReplyRequest = Body(...)) -> bool:
    return await PermissionService.reply(request_id, payload.model_dump(exclude_none=True))


router = crud_router(
    prefix="/v1/permissions",
    tags=["permissions"],
    routes=[
        raw("GET", "", list[dict[str, object]], list_permissions),
        raw("POST", "/{request_id}/reply", bool, reply_permission),
    ],
)
