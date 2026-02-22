"""Preference transport routes."""

from __future__ import annotations

from fastapi import Body

from ...app_services import PreferenceService
from ..schemas import PreferenceCurrentResponse, PreferenceCurrentUpdateRequest
from .crud import crud_router, one


async def get_current_preference() -> dict[str, object]:
    return await PreferenceService.get_current()


async def update_current_preference(
    payload: PreferenceCurrentUpdateRequest = Body(...),
) -> dict[str, object]:
    return await PreferenceService.update_current(payload.model_dump(exclude_unset=True))


router = crud_router(
    prefix="/v1/preferences",
    tags=["preferences"],
    routes=[
        one("GET", "/current", PreferenceCurrentResponse, get_current_preference),
        one("PATCH", "/current", PreferenceCurrentResponse, update_current_preference),
    ],
)
