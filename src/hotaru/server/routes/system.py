"""System and static asset transport routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from starlette.responses import Response
from starlette.responses import FileResponse, HTMLResponse

from ...app_services.errors import NotFoundError
from ...core.global_paths import GlobalPath
from ...skill import Skill
from ..deps import resolve_request_directory
from ..schemas import HealthResponse, PathsResponse, SkillResponse, WebHealthResponse, WebReadyResponse
from ..webui import web_asset_path, web_dist_path, web_index_response

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()


@router.get("/healthz/web", response_model=WebHealthResponse)
async def health_web() -> WebHealthResponse:
    return WebHealthResponse(web=WebReadyResponse(ready=web_dist_path() is not None))


@router.get("/", include_in_schema=False, response_model=None)
async def web_index() -> Response:
    return web_index_response()


@router.get("/web", include_in_schema=False, response_model=None)
async def web_index_alias() -> Response:
    return web_index_response()


@router.get("/web/{path:path}", include_in_schema=False, response_model=None)
async def web_asset(path: str) -> Response:
    target = web_asset_path(path)
    if target is None:
        return web_index_response()
    return FileResponse(target)


@router.get("/assets/{path:path}", include_in_schema=False, response_model=None)
async def web_root_asset(path: str) -> Response:
    target = web_asset_path(f"assets/{str(path).strip()}")
    if target is None:
        raise NotFoundError("Web asset", path)
    return FileResponse(target)


@router.get("/v1/path", response_model=PathsResponse)
async def get_paths(cwd: str = Depends(resolve_request_directory)) -> PathsResponse:
    return PathsResponse(
        home=str(GlobalPath.home()),
        state=str(GlobalPath.state()),
        config=str(GlobalPath.config()),
        cwd=cwd,
    )


@router.get("/v1/skill", response_model=list[SkillResponse])
async def list_skills() -> list[SkillResponse]:
    skills = await Skill.list()
    return [
        SkillResponse(name=skill.name, description=skill.description, location=skill.location)
        for skill in skills
    ]
