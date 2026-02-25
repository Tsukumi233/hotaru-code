"""Provider transport routes."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends

from ...app_services import ProviderService
from ..deps import resolve_request_directory
from ..schemas import (
    ProviderConnectRequest,
    ProviderConnectResponse,
    ProviderModelResponse,
    ProviderResponse,
)

router = APIRouter(prefix="/v1/providers", tags=["providers"])


@router.get("", response_model=list[ProviderResponse])
async def list_providers(
    cwd: str = Depends(resolve_request_directory),
) -> list[dict[str, object]]:
    return await ProviderService.list(cwd)


@router.get("/{provider_id}/models", response_model=list[ProviderModelResponse])
async def list_models(
    provider_id: str,
    cwd: str = Depends(resolve_request_directory),
) -> list[dict[str, object]]:
    return await ProviderService.list_models(provider_id, cwd)


@router.post("/connect", response_model=ProviderConnectResponse)
async def connect_provider(payload: ProviderConnectRequest = Body(...)) -> dict[str, object]:
    return await ProviderService.connect(payload.model_dump(exclude_none=True))
