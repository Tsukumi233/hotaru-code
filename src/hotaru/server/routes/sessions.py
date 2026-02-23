"""Session transport routes."""

from __future__ import annotations

from fastapi import Body, Depends, Query

from ...app_services import SessionService
from ...app_services.errors import NotFoundError
from ...runtime import AppContext
from ..deps import resolve_app_context, resolve_request_directory
from ..schemas import (
    SessionCompactRequest,
    SessionCreateRequest,
    SessionDeleteMessagesRequest,
    SessionDeleteMessagesResponse,
    SessionDeleteResponse,
    SessionListMessageResponse,
    SessionMessageRequest,
    SessionMessageResponse,
    SessionResponse,
    SessionRestoreMessagesRequest,
    SessionRestoreMessagesResponse,
    SessionUpdateRequest,
)
from .crud import crud_router, many, one


async def create_session(
    payload: SessionCreateRequest | None = Body(default=None),
    cwd: str = Depends(resolve_request_directory),
    app: AppContext = Depends(resolve_app_context),
) -> dict[str, object]:
    return await SessionService.create((payload.model_dump(exclude_none=True) if payload else {}), cwd, app=app)


async def list_sessions(
    project_id: str | None = Query(default=None),
    cwd: str = Depends(resolve_request_directory),
) -> list[dict[str, object]]:
    return await SessionService.list(project_id, cwd)


async def get_session(session_id: str) -> dict[str, object]:
    if not (item := await SessionService.get(session_id)):
        raise NotFoundError("Session", session_id)
    return item


async def update_session(
    session_id: str,
    payload: SessionUpdateRequest = Body(...),
) -> dict[str, object]:
    if not (item := await SessionService.update(session_id, payload.model_dump(exclude_none=True))):
        raise NotFoundError("Session", session_id)
    return item


async def delete_session(
    session_id: str,
    ctx: AppContext = Depends(resolve_app_context),
) -> dict[str, object]:
    return await SessionService.delete(session_id, app=ctx)


async def list_messages(session_id: str) -> list[dict[str, object]]:
    return await SessionService.list_messages(session_id)


async def message_session(
    session_id: str,
    payload: SessionMessageRequest = Body(...),
    cwd: str = Depends(resolve_request_directory),
    ctx: AppContext = Depends(resolve_app_context),
) -> dict[str, object]:
    return await SessionService.message(session_id, payload.model_dump(exclude_none=True), cwd, app=ctx)


async def interrupt_session(
    session_id: str,
    ctx: AppContext = Depends(resolve_app_context),
) -> dict[str, object]:
    return await SessionService.interrupt(session_id, app=ctx)


async def compact_session(
    session_id: str,
    payload: SessionCompactRequest | None = Body(default=None),
    cwd: str = Depends(resolve_request_directory),
    ctx: AppContext = Depends(resolve_app_context),
) -> dict[str, object]:
    return await SessionService.compact(
        session_id,
        (payload.model_dump(exclude_none=True) if payload else {}),
        cwd,
        app=ctx,
    )


async def delete_messages(
    session_id: str,
    payload: SessionDeleteMessagesRequest = Body(...),
) -> dict[str, object]:
    return await SessionService.delete_messages(session_id, payload.model_dump(exclude_none=True))


async def restore_messages(
    session_id: str,
    payload: SessionRestoreMessagesRequest = Body(...),
) -> dict[str, object]:
    return await SessionService.restore_messages(session_id, payload.model_dump(exclude_none=True))


router = crud_router(
    prefix="/v1/sessions",
    tags=["sessions"],
    routes=[
        one("POST", "", SessionResponse, create_session),
        many("GET", "", SessionResponse, list_sessions),
        one("GET", "/{session_id}", SessionResponse, get_session),
        one("PATCH", "/{session_id}", SessionResponse, update_session),
        one("DELETE", "/{session_id}", SessionDeleteResponse, delete_session),
        many("GET", "/{session_id}/messages", SessionListMessageResponse, list_messages),
        one("POST", "/{session_id}/messages", SessionMessageResponse, message_session),
        one("POST", "/{session_id}/interrupt", SessionMessageResponse, interrupt_session),
        one("POST", "/{session_id}/compact", SessionMessageResponse, compact_session),
        one("DELETE", "/{session_id}/messages", SessionDeleteMessagesResponse, delete_messages),
        one("POST", "/{session_id}/messages/restore", SessionRestoreMessagesResponse, restore_messages),
    ],
)
