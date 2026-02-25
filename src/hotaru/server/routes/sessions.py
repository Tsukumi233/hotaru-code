"""Session transport routes."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Query

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

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])


@router.post("", response_model=SessionResponse)
async def create_session(
    payload: SessionCreateRequest | None = Body(default=None),
    cwd: str = Depends(resolve_request_directory),
    app: AppContext = Depends(resolve_app_context),
) -> dict[str, object]:
    return await SessionService.create((payload.model_dump(exclude_none=True) if payload else {}), cwd, app=app)


@router.get("", response_model=list[SessionResponse])
async def list_sessions(
    project_id: str | None = Query(default=None),
    cwd: str = Depends(resolve_request_directory),
) -> list[dict[str, object]]:
    return await SessionService.list(project_id, cwd)


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str) -> dict[str, object]:
    if not (item := await SessionService.get(session_id)):
        raise NotFoundError("Session", session_id)
    return item


@router.patch("/{session_id}", response_model=SessionResponse)
async def update_session(
    session_id: str,
    payload: SessionUpdateRequest = Body(...),
) -> dict[str, object]:
    if not (item := await SessionService.update(session_id, payload.model_dump(exclude_none=True))):
        raise NotFoundError("Session", session_id)
    return item


@router.delete("/{session_id}", response_model=SessionDeleteResponse)
async def delete_session(
    session_id: str,
    ctx: AppContext = Depends(resolve_app_context),
) -> dict[str, object]:
    return await SessionService.delete(session_id, app=ctx)


@router.get("/{session_id}/messages", response_model=list[SessionListMessageResponse])
async def list_messages(session_id: str) -> list[dict[str, object]]:
    return await SessionService.list_messages(session_id)


@router.post("/{session_id}/messages", response_model=SessionMessageResponse)
async def message_session(
    session_id: str,
    payload: SessionMessageRequest = Body(...),
    cwd: str = Depends(resolve_request_directory),
    ctx: AppContext = Depends(resolve_app_context),
) -> dict[str, object]:
    return await SessionService.message(session_id, payload.model_dump(exclude_none=True), cwd, app=ctx)


@router.post("/{session_id}/interrupt", response_model=SessionMessageResponse)
async def interrupt_session(
    session_id: str,
    ctx: AppContext = Depends(resolve_app_context),
) -> dict[str, object]:
    return await SessionService.interrupt(session_id, app=ctx)


@router.post("/{session_id}/compact", response_model=SessionMessageResponse)
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


@router.delete("/{session_id}/messages", response_model=SessionDeleteMessagesResponse)
async def delete_messages(
    session_id: str,
    payload: SessionDeleteMessagesRequest = Body(...),
) -> dict[str, object]:
    return await SessionService.delete_messages(session_id, payload.model_dump(exclude_none=True))


@router.post("/{session_id}/messages/restore", response_model=SessionRestoreMessagesResponse)
async def restore_messages(
    session_id: str,
    payload: SessionRestoreMessagesRequest = Body(...),
) -> dict[str, object]:
    return await SessionService.restore_messages(session_id, payload.model_dump(exclude_none=True))
