"""MCP transport routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends

from ...app_services import McpService
from ...runtime import AppContext
from ..deps import resolve_app_context
from ..schemas import (
    McpAuthCallbackRequest,
    McpAuthRemoveResponse,
    McpAuthStartResponse,
    McpConnectResponse,
)

router = APIRouter(prefix="/v1/mcp", tags=["mcp"])


@router.get("", response_model=dict[str, dict[str, Any]])
async def status(
    app: AppContext = Depends(resolve_app_context),
) -> dict[str, dict[str, Any]]:
    return await McpService.status(app)


@router.post("/{name}/connect", response_model=McpConnectResponse)
async def connect(
    name: str,
    app: AppContext = Depends(resolve_app_context),
) -> dict[str, bool]:
    return await McpService.connect(app, name)


@router.post("/{name}/disconnect", response_model=McpConnectResponse)
async def disconnect(
    name: str,
    app: AppContext = Depends(resolve_app_context),
) -> dict[str, bool]:
    return await McpService.disconnect(app, name)


@router.post("/{name}/auth/start", response_model=McpAuthStartResponse)
async def auth_start(
    name: str,
    app: AppContext = Depends(resolve_app_context),
) -> dict[str, str]:
    return await McpService.auth_start(app, name)


@router.post("/{name}/auth/callback", response_model=dict[str, Any])
async def auth_callback(
    name: str,
    payload: McpAuthCallbackRequest = Body(...),
    app: AppContext = Depends(resolve_app_context),
) -> dict[str, Any]:
    data = payload.model_dump(exclude_none=True)
    return await McpService.auth_callback(
        app,
        name,
        code=str(data["code"]),
        state=str(data["state"]),
    )


@router.post("/{name}/auth/authenticate", response_model=dict[str, Any])
async def auth_authenticate(
    name: str,
    app: AppContext = Depends(resolve_app_context),
) -> dict[str, Any]:
    return await McpService.auth_authenticate(app, name)


@router.delete("/{name}/auth", response_model=McpAuthRemoveResponse)
async def auth_remove(
    name: str,
    app: AppContext = Depends(resolve_app_context),
) -> dict[str, bool]:
    return await McpService.auth_remove(app, name)
