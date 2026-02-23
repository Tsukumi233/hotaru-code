"""HTTP server lifecycle management for FastAPI app."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from ..runtime import AppContext
from ..storage import Storage
from ..util.log import Log
from .app import create_app
from .webui import web_dist_candidates

log = Log.create({"service": "server"})

DEFAULT_PORT = 4096


@dataclass
class ServerInfo:
    host: str
    port: int

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"


class Server:
    _app: FastAPI | None = None
    _server: Any | None = None
    _info: ServerInfo | None = None
    _ctx: AppContext | None = None
    _task: asyncio.Task[Any] | None = None

    @classmethod
    def _create_app(
        cls,
        ctx: AppContext,
        *,
        manage_lifecycle: bool = False,
    ) -> FastAPI:
        """Build a FastAPI app with an explicit application context."""
        return create_app(ctx, manage_lifecycle=manage_lifecycle)

    @classmethod
    def _web_dist_candidates(cls) -> list[Path]:
        return web_dist_candidates()

    @classmethod
    async def start(
        cls,
        host: str = "127.0.0.1",
        port: int = DEFAULT_PORT,
    ) -> ServerInfo:
        import uvicorn

        await Storage.initialize()
        cls._ctx = AppContext()
        cls._app = cls._create_app(cls._ctx, manage_lifecycle=True)

        config = uvicorn.Config(
            cls._app,
            host=host,
            port=port,
            log_level="warning",
        )

        cls._server = uvicorn.Server(config)
        cls._info = ServerInfo(host=host, port=port)

        log.info("starting server", {"host": host, "port": port})
        cls._task = asyncio.create_task(cls._server.serve())

        while not cls._server.started and not cls._task.done():
            await asyncio.sleep(0.1)

        log.info("server started", {"url": cls._info.url})
        return cls._info

    @classmethod
    async def stop(cls) -> None:
        server = cls._server
        if not server:
            return

        log.info("stopping server")
        server.should_exit = True
        task = cls._task
        while bool(getattr(server, "started", False)) and not (task and task.done()):
            await asyncio.sleep(0.05)

        if cls._server is server:
            cls._server = None
            cls._app = None
            cls._info = None
            cls._ctx = None
            cls._task = None
        log.info("server stopped")

    @classmethod
    def info(cls) -> ServerInfo | None:
        return cls._info
