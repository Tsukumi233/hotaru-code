"""HTTP server lifecycle management for FastAPI app."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI

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

    @classmethod
    def _create_app(cls) -> FastAPI:
        return create_app()

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

        cls._app = cls._create_app()

        config = uvicorn.Config(
            cls._app,
            host=host,
            port=port,
            log_level="warning",
        )

        cls._server = uvicorn.Server(config)
        cls._info = ServerInfo(host=host, port=port)

        log.info("starting server", {"host": host, "port": port})
        asyncio.create_task(cls._server.serve())

        while not cls._server.started:
            await asyncio.sleep(0.1)

        log.info("server started", {"url": cls._info.url})
        return cls._info

    @classmethod
    async def stop(cls) -> None:
        if cls._server:
            log.info("stopping server")
            cls._server.should_exit = True
            await asyncio.sleep(0.5)
            cls._server = None
            cls._app = None
            cls._info = None
            log.info("server stopped")

    @classmethod
    def info(cls) -> ServerInfo | None:
        return cls._info
