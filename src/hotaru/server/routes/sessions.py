"""Session transport routes."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Query

from ...app_services import SessionService
from ..deps import resolve_request_directory
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
) -> SessionResponse:
    result = await SessionService.create((payload.model_dump(exclude_none=True) if payload else {}), cwd)
    return SessionResponse.model_validate(result)


@router.get("", response_model=list[SessionResponse])
async def list_sessions(
    project_id: str | None = Query(default=None),
    cwd: str = Depends(resolve_request_directory),
) -> list[SessionResponse]:
    result = await SessionService.list(project_id, cwd)
    return [SessionResponse.model_validate(item) for item in result]


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str) -> SessionResponse:
    result = await SessionService.get(session_id)
    if not result:
        raise KeyError(f"Session '{session_id}' not found")
    return SessionResponse.model_validate(result)


@router.patch("/{session_id}", response_model=SessionResponse)
async def update_session(
    session_id: str,
    payload: SessionUpdateRequest = Body(...),
) -> SessionResponse:
    result = await SessionService.update(session_id, payload.model_dump(exclude_none=True))
    if not result:
        raise KeyError(f"Session '{session_id}' not found")
    return SessionResponse.model_validate(result)


@router.delete("/{session_id}", response_model=SessionDeleteResponse)
async def delete_session(session_id: str) -> SessionDeleteResponse:
    result = await SessionService.delete(session_id)
    return SessionDeleteResponse.model_validate(result)


@router.get("/{session_id}/messages", response_model=list[SessionListMessageResponse])
async def list_messages(session_id: str) -> list[SessionListMessageResponse]:
    result = await SessionService.list_messages(session_id)
    return [SessionListMessageResponse.model_validate(item) for item in result]


@router.post("/{session_id}/messages", response_model=SessionMessageResponse)
async def message_session(
    session_id: str,
    payload: SessionMessageRequest = Body(...),
    cwd: str = Depends(resolve_request_directory),
) -> SessionMessageResponse:
    result = await SessionService.message(session_id, payload.model_dump(exclude_none=True), cwd)
    return SessionMessageResponse.model_validate(result)


@router.post("/{session_id}/interrupt", response_model=SessionMessageResponse)
async def interrupt_session(session_id: str) -> SessionMessageResponse:
    result = await SessionService.interrupt(session_id)
    return SessionMessageResponse.model_validate(result)


@router.post("/{session_id}/compact", response_model=SessionMessageResponse)
async def compact_session(
    session_id: str,
    payload: SessionCompactRequest | None = Body(default=None),
    cwd: str = Depends(resolve_request_directory),
) -> SessionMessageResponse:
    result = await SessionService.compact(session_id, (payload.model_dump(exclude_none=True) if payload else {}), cwd)
    return SessionMessageResponse.model_validate(result)


@router.delete("/{session_id}/messages", response_model=SessionDeleteMessagesResponse)
async def delete_messages(
    session_id: str,
    payload: SessionDeleteMessagesRequest = Body(...),
) -> SessionDeleteMessagesResponse:
    result = await SessionService.delete_messages(session_id, payload.model_dump(exclude_none=True))
    return SessionDeleteMessagesResponse.model_validate(result)


@router.post("/{session_id}/messages/restore", response_model=SessionRestoreMessagesResponse)
async def restore_messages(
    session_id: str,
    payload: SessionRestoreMessagesRequest = Body(...),
) -> SessionRestoreMessagesResponse:
    result = await SessionService.restore_messages(session_id, payload.model_dump(exclude_none=True))
    return SessionRestoreMessagesResponse.model_validate(result)
