"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .errors import register_error_handlers
from .routes import agents, events, permissions, preferences, providers, ptys, questions, sessions, system
from .schemas import ErrorResponse


def create_app() -> FastAPI:
    app = FastAPI(
        title="Hotaru Code API",
        version="1.0.0",
        openapi_version="3.1.0",
        responses={
            400: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
            500: {"model": ErrorResponse},
        },
    )

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
