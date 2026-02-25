"""Preference transport routes."""

from __future__ import annotations

from fastapi import APIRouter, Body

from ...app_services import PreferenceService
from ..schemas import PreferenceCurrentResponse, PreferenceCurrentUpdateRequest

router = APIRouter(prefix="/v1/preferences", tags=["preferences"])


@router.get("/current", response_model=PreferenceCurrentResponse)
async def get_current_preference() -> dict[str, object]:
    return await PreferenceService.get_current()


@router.patch("/current", response_model=PreferenceCurrentResponse)
async def update_current_preference(
    payload: PreferenceCurrentUpdateRequest = Body(...),
) -> dict[str, object]:
    return await PreferenceService.update_current(payload.model_dump(exclude_unset=True))
