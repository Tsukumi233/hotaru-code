"""HTTP server for Hotaru Code API.

This module provides an HTTP API server that exposes Hotaru Code functionality
to external clients (IDEs, web interfaces, etc.).

The server provides:
- Session management endpoints
- Provider and model information
- Event streaming via SSE
- File operations
- Configuration management

Example:
    from hotaru.server import Server

    # Start the server
    server = await Server.start(port=4096)

    # Get the server URL
    print(f"Server running at {server.url}")

    # Stop the server
    await server.stop()
"""

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from ..agent import Agent
from ..core.bus import Bus
from ..core.config import ConfigManager
from ..core.global_paths import GlobalPath
from ..provider import Provider
from ..session import Session
from ..skill import Skill
from ..util.log import Log

log = Log.create({"service": "server"})

# Default server port
DEFAULT_PORT = 4096


@dataclass
class ServerInfo:
    """Information about a running server.

    Attributes:
        host: Server hostname
        port: Server port
        url: Full server URL
    """
    host: str
    port: int

    @property
    def url(self) -> str:
        """Get the full server URL."""
        return f"http://{self.host}:{self.port}"


class Server:
    """HTTP API server for Hotaru Code.

    Provides REST API endpoints for external clients to interact
    with Hotaru Code functionality.
    """

    _app: Optional[Starlette] = None
    _server: Optional[Any] = None
    _info: Optional[ServerInfo] = None

    @classmethod
    def _create_app(cls) -> Starlette:
        """Create the Starlette application with routes.

        Returns:
            Configured Starlette application
        """
        routes = [
            # Health check
            Route("/health", cls._health, methods=["GET"]),

            # Path information
            Route("/path", cls._get_paths, methods=["GET"]),

            # Provider endpoints
            Route("/provider", cls._list_providers, methods=["GET"]),
            Route("/provider/{provider_id}/model", cls._list_models, methods=["GET"]),

            # Agent endpoints
            Route("/agent", cls._list_agents, methods=["GET"]),

            # Skill endpoints
            Route("/skill", cls._list_skills, methods=["GET"]),

            # Session endpoints
            Route("/session", cls._list_sessions, methods=["GET"]),
            Route("/session/{session_id}", cls._get_session, methods=["GET"]),

            # Event stream
            Route("/event", cls._event_stream, methods=["GET"]),
        ]

        middleware = [
            Middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_methods=["*"],
                allow_headers=["*"],
            ),
        ]

        return Starlette(
            routes=routes,
            middleware=middleware,
            on_startup=[cls._on_startup],
            on_shutdown=[cls._on_shutdown],
        )

    @classmethod
    async def _on_startup(cls) -> None:
        """Called when the server starts."""
        log.info("server starting")

    @classmethod
    async def _on_shutdown(cls) -> None:
        """Called when the server stops."""
        log.info("server stopping")

    # Route handlers

    @classmethod
    async def _health(cls, request: Request) -> JSONResponse:
        """Health check endpoint."""
        return JSONResponse({"status": "ok"})

    @classmethod
    async def _get_paths(cls, request: Request) -> JSONResponse:
        """Get path information."""
        import os
        return JSONResponse({
            "home": str(GlobalPath.home()),
            "state": str(GlobalPath.state()),
            "config": str(GlobalPath.config()),
            "cwd": os.getcwd(),
        })

    @classmethod
    async def _list_providers(cls, request: Request) -> JSONResponse:
        """List available providers."""
        providers = await Provider.list()
        result = []
        for provider_id, provider in providers.items():
            result.append({
                "id": provider.id,
                "name": provider.name,
                "source": provider.source.value if provider.source else None,
                "model_count": len(provider.models),
            })
        return JSONResponse(result)

    @classmethod
    async def _list_models(cls, request: Request) -> JSONResponse:
        """List models for a provider."""
        provider_id = request.path_params["provider_id"]
        provider = await Provider.get(provider_id)

        if not provider:
            return JSONResponse(
                {"error": f"Provider '{provider_id}' not found"},
                status_code=404,
            )

        models = []
        for model_id, model in provider.models.items():
            models.append({
                "id": model.id,
                "name": model.name,
                "api_id": model.api_id,
                "status": model.status,
            })

        return JSONResponse(models)

    @classmethod
    async def _list_agents(cls, request: Request) -> JSONResponse:
        """List available agents."""
        agents = await Agent.list()
        result = []
        for agent in agents:
            result.append({
                "name": agent.name,
                "description": agent.description,
                "mode": agent.mode,
            })
        return JSONResponse(result)

    @classmethod
    async def _list_skills(cls, request: Request) -> JSONResponse:
        """List available skills."""
        skills = await Skill.list()
        result = []
        for skill in skills:
            result.append({
                "name": skill.name,
                "description": skill.description,
                "location": skill.location,
            })
        return JSONResponse(result)

    @classmethod
    async def _list_sessions(cls, request: Request) -> JSONResponse:
        """List sessions."""
        # Get project_id from query params
        project_id = request.query_params.get("project_id")
        if not project_id:
            return JSONResponse(
                {"error": "project_id query parameter required"},
                status_code=400,
            )

        sessions = await Session.list(project_id)
        result = []
        for session in sessions:
            result.append({
                "id": session.id,
                "project_id": session.project_id,
                "agent": session.agent,
                "model_id": session.model_id,
                "provider_id": session.provider_id,
                "created": session.created,
            })
        return JSONResponse(result)

    @classmethod
    async def _get_session(cls, request: Request) -> JSONResponse:
        """Get a specific session."""
        session_id = request.path_params["session_id"]
        session = await Session.get(session_id)

        if not session:
            return JSONResponse(
                {"error": f"Session '{session_id}' not found"},
                status_code=404,
            )

        return JSONResponse({
            "id": session.id,
            "project_id": session.project_id,
            "agent": session.agent,
            "model_id": session.model_id,
            "provider_id": session.provider_id,
            "created": session.created,
        })

    @classmethod
    async def _event_stream(cls, request: Request) -> StreamingResponse:
        """Server-Sent Events stream for real-time updates."""
        async def event_generator():
            # Send initial connected event
            yield f"data: {json.dumps({'type': 'server.connected'})}\n\n"

            # Subscribe to bus events
            queue: asyncio.Queue = asyncio.Queue()

            def on_event(event: Dict[str, Any]) -> None:
                asyncio.create_task(queue.put(event))

            # Note: In a full implementation, we would subscribe to Bus events
            # For now, just send heartbeats
            try:
                while True:
                    try:
                        # Wait for events with timeout for heartbeat
                        event = await asyncio.wait_for(queue.get(), timeout=30.0)
                        yield f"data: {json.dumps(event)}\n\n"
                    except asyncio.TimeoutError:
                        # Send heartbeat
                        yield f"data: {json.dumps({'type': 'server.heartbeat'})}\n\n"
            except asyncio.CancelledError:
                pass

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    @classmethod
    async def start(
        cls,
        host: str = "127.0.0.1",
        port: int = DEFAULT_PORT,
    ) -> ServerInfo:
        """Start the HTTP server.

        Args:
            host: Hostname to bind to
            port: Port to listen on

        Returns:
            ServerInfo with connection details
        """
        import uvicorn

        cls._app = cls._create_app()

        # Create server config
        config = uvicorn.Config(
            cls._app,
            host=host,
            port=port,
            log_level="warning",
        )

        cls._server = uvicorn.Server(config)
        cls._info = ServerInfo(host=host, port=port)

        log.info("starting server", {"host": host, "port": port})

        # Start server in background
        asyncio.create_task(cls._server.serve())

        # Wait for server to be ready
        while not cls._server.started:
            await asyncio.sleep(0.1)

        log.info("server started", {"url": cls._info.url})

        return cls._info

    @classmethod
    async def stop(cls) -> None:
        """Stop the HTTP server."""
        if cls._server:
            log.info("stopping server")
            cls._server.should_exit = True
            await asyncio.sleep(0.5)  # Give time for graceful shutdown
            cls._server = None
            cls._app = None
            cls._info = None
            log.info("server stopped")

    @classmethod
    def info(cls) -> Optional[ServerInfo]:
        """Get information about the running server.

        Returns:
            ServerInfo if server is running, None otherwise
        """
        return cls._info
