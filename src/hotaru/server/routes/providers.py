"""Provider transport routes."""

from __future__ import annotations

from fastapi import Body, Depends

from ...app_services import ProviderService
from ..deps import resolve_request_directory
from ..schemas import (
    ProviderConnectRequest,
    ProviderConnectResponse,
    ProviderModelResponse,
    ProviderResponse,
)
from .crud import crud_router, many, one


async def list_providers(
    cwd: str = Depends(resolve_request_directory),
) -> list[dict[str, object]]:
    return await ProviderService.list(cwd)


async def list_models(
    provider_id: str,
    cwd: str = Depends(resolve_request_directory),
) -> list[dict[str, object]]:
    return await ProviderService.list_models(provider_id, cwd)


async def connect_provider(payload: ProviderConnectRequest = Body(...)) -> dict[str, object]:
    return await ProviderService.connect(payload.model_dump(exclude_none=True))


router = crud_router(
    prefix="/v1/providers",
    tags=["providers"],
    routes=[
        many("GET", "", ProviderResponse, list_providers),
        many("GET", "/{provider_id}/models", ProviderModelResponse, list_models),
        one("POST", "/connect", ProviderConnectResponse, connect_provider),
    ],
)
