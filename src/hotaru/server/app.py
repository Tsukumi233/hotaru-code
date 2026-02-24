"""FastAPI application factory."""

from __future__ import annotations

import secrets
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from ..core.bus import Bus
from ..runtime import AppContext
from ..util.log import Log
from .errors import register_error_handlers
from .routes import agents, events, permissions, preferences, providers, ptys, questions, sessions, system
from .schemas import ErrorResponse

access = Log.create({"service": "server.access"})


def create_app(
    ctx: AppContext,
    *,
    manage_lifecycle: bool = False,
    access_log: bool = True,
) -> FastAPI:
    """Create a FastAPI application.

    ``ctx`` is the application-level service container.  It must be provided
    by all callers — entry-points create it via ``AppContext()``.
    """

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        await ctx.startup()
        try:
            yield
        finally:
            await ctx.shutdown()

    app = FastAPI(
        title="Hotaru Code API",
        version="1.0.0",
        openapi_version="3.1.0",
        lifespan=_lifespan if manage_lifecycle else None,
        responses={
            400: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
            500: {"model": ErrorResponse},
        },
    )
    app.state.ctx = ctx

    @app.middleware("http")
    async def _bind_bus_for_request(request: Request, call_next):
        token = Bus.provide(ctx.bus)
        try:
            return await call_next(request)
        finally:
            Bus.restore(token)

    @app.middleware("http")
    async def _access_log(request: Request, call_next):
        rid = request.headers.get("x-request-id") or secrets.token_hex(8)
        request.state.request_id = rid
        begin = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as e:
            if access_log:
                access.error(
                    "request failed",
                    {
                        "request_id": rid,
                        "method": request.method,
                        "path": request.url.path,
                        "query": request.url.query or None,
                        "client_ip": request.client.host if request.client else None,
                        "duration_ms": int((time.perf_counter() - begin) * 1000),
                        "error": str(e),
                    },
                )
            raise
        response.headers["X-Request-ID"] = rid
        if not access_log:
            return response
        access.info(
            "request",
            {
                "request_id": rid,
                "method": request.method,
                "path": request.url.path,
                "query": request.url.query or None,
                "status": response.status_code,
                "client_ip": request.client.host if request.client else None,
                "duration_ms": int((time.perf_counter() - begin) * 1000),
            },
        )
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_error_handlers(app)

    app.include_router(system.router)
    app.include_router(sessions.router)
    app.include_router(providers.router)
    app.include_router(agents.router)
    app.include_router(preferences.router)
    app.include_router(permissions.router)
    app.include_router(questions.router)
    app.include_router(events.router)
    app.include_router(ptys.router)
    return app
