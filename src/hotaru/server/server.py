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
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from ..app_services import (
    AgentService,
    EventService,
    PermissionService,
    ProviderService,
    QuestionService,
    SessionService,
)
from ..agent import Agent
from ..core.bus import Bus
from ..core.global_paths import GlobalPath
from ..provider import Provider
from ..session import Session, SessionCompaction, SessionPrompt
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

            # Versioned v1 endpoints
            Route("/v1/session", cls._v1_create_session, methods=["POST"]),
            Route("/v1/session", cls._v1_list_sessions, methods=["GET"]),
            Route("/v1/session/{id}", cls._v1_get_session, methods=["GET"]),
            Route("/v1/session/{id}/compact", cls._v1_compact_session, methods=["POST"]),
            Route("/v1/session/{id}/message:stream", cls._v1_message_stream, methods=["POST"]),
            Route("/v1/provider", cls._v1_list_providers, methods=["GET"]),
            Route("/v1/provider/{id}/model", cls._v1_list_models, methods=["GET"]),
            Route("/v1/provider/connect", cls._v1_connect_provider, methods=["POST"]),
            Route("/v1/agent", cls._v1_list_agents, methods=["GET"]),
            Route("/v1/permission", cls._v1_list_permissions, methods=["GET"]),
            Route("/v1/permission/{id}/reply", cls._v1_reply_permission, methods=["POST"]),
            Route("/v1/question", cls._v1_list_questions, methods=["GET"]),
            Route("/v1/question/{id}/reply", cls._v1_reply_question, methods=["POST"]),
            Route("/v1/question/{id}/reject", cls._v1_reject_question, methods=["POST"]),
            Route("/v1/event", cls._v1_event_stream, methods=["GET"]),

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
            Route("/session/{session_id}/summarize", cls._summarize_session, methods=["POST"]),
            Route("/permission", cls._list_permissions, methods=["GET"]),
            Route("/permission/{request_id}/reply", cls._reply_permission, methods=["POST"]),
            Route("/question", cls._list_questions, methods=["GET"]),
            Route("/question/{request_id}/reply", cls._reply_question, methods=["POST"]),
            Route("/question/{request_id}/reject", cls._reject_question, methods=["POST"]),

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

    @staticmethod
    def _now_ms() -> int:
        import time
        return int(time.time() * 1000)

    @classmethod
    def _error_response(
        cls,
        *,
        status_code: int,
        code: str,
        message: str,
        details: Optional[dict[str, Any]] = None,
    ) -> JSONResponse:
        payload: dict[str, Any] = {
            "error": {
                "code": code,
                "message": message,
            }
        }
        if details is not None:
            payload["error"]["details"] = details
        return JSONResponse(payload, status_code=status_code)

    @classmethod
    def _error_from_exception(cls, exc: Exception) -> JSONResponse:
        if isinstance(exc, ValueError):
            return cls._error_response(
                status_code=400,
                code="bad_request",
                message=str(exc),
            )
        if isinstance(exc, KeyError):
            message = str(exc)
            if message.startswith("'") and message.endswith("'"):
                message = message[1:-1]
            return cls._error_response(
                status_code=404,
                code="not_found",
                message=message,
            )
        log.error("v1 route failed", {"error": str(exc)})
        return cls._error_response(
            status_code=500,
            code="internal_error",
            message="Internal server error",
            details={"error": str(exc)},
        )

    @classmethod
    async def _json_payload(cls, request: Request, *, required: bool = False) -> dict[str, Any]:
        try:
            payload = await request.json()
        except Exception:
            if required:
                raise ValueError("Request body must be a JSON object")
            return {}

        if payload is None and not required:
            return {}
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object")
        return payload

    @classmethod
    def _sse_data(
        cls,
        event: dict[str, Any],
        *,
        session_id: Optional[str] = None,
    ) -> str:
        event_type = str(event.get("type", "server.event"))
        data = event.get("data", {})
        if not isinstance(data, dict):
            data = {"value": data}
        envelope: dict[str, Any] = {
            "type": event_type,
            "data": data,
            "timestamp": cls._now_ms(),
        }
        if session_id:
            envelope["session_id"] = session_id
        return f"data: {json.dumps(envelope)}\n\n"

    @classmethod
    def _sse_response(cls, iterator: Any) -> StreamingResponse:
        return StreamingResponse(
            iterator,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    # v1 transport handlers

    @classmethod
    async def _v1_create_session(cls, request: Request) -> JSONResponse:
        try:
            payload = await cls._json_payload(request, required=False)
            result = await SessionService.create(payload, str(Path.cwd()))
            return JSONResponse(result)
        except Exception as exc:
            return cls._error_from_exception(exc)

    @classmethod
    async def _v1_list_sessions(cls, request: Request) -> JSONResponse:
        project_id = request.query_params.get("project_id", "")
        try:
            result = await SessionService.list(project_id)
            return JSONResponse(result)
        except Exception as exc:
            return cls._error_from_exception(exc)

    @classmethod
    async def _v1_get_session(cls, request: Request) -> JSONResponse:
        session_id = request.path_params["id"]
        try:
            result = await SessionService.get(session_id)
            if result is None:
                return cls._error_response(
                    status_code=404,
                    code="not_found",
                    message=f"Session '{session_id}' not found",
                )
            return JSONResponse(result)
        except Exception as exc:
            return cls._error_from_exception(exc)

    @classmethod
    async def _v1_compact_session(cls, request: Request) -> JSONResponse:
        session_id = request.path_params["id"]
        try:
            payload = await cls._json_payload(request, required=False)
            result = await SessionService.compact(session_id, payload, str(Path.cwd()))
            return JSONResponse(result)
        except Exception as exc:
            return cls._error_from_exception(exc)

    @classmethod
    async def _v1_message_stream(cls, request: Request) -> StreamingResponse | JSONResponse:
        session_id = request.path_params["id"]
        try:
            payload = await cls._json_payload(request, required=True)
            stream = SessionService.stream_message(session_id, payload, str(Path.cwd()))
        except Exception as exc:
            return cls._error_from_exception(exc)

        async def event_generator():
            try:
                async for event in stream:
                    yield cls._sse_data(event, session_id=session_id)
            except Exception as exc:
                yield cls._sse_data(
                    {"type": "error", "data": {"error": str(exc)}},
                    session_id=session_id,
                )

        return cls._sse_response(event_generator())

    @classmethod
    async def _v1_list_providers(cls, request: Request) -> JSONResponse:
        try:
            return JSONResponse(await ProviderService.list())
        except Exception as exc:
            return cls._error_from_exception(exc)

    @classmethod
    async def _v1_list_models(cls, request: Request) -> JSONResponse:
        provider_id = request.path_params["id"]
        try:
            return JSONResponse(await ProviderService.list_models(provider_id))
        except Exception as exc:
            return cls._error_from_exception(exc)

    @classmethod
    async def _v1_connect_provider(cls, request: Request) -> JSONResponse:
        try:
            payload = await cls._json_payload(request, required=True)
            return JSONResponse(await ProviderService.connect(payload))
        except Exception as exc:
            return cls._error_from_exception(exc)

    @classmethod
    async def _v1_list_agents(cls, request: Request) -> JSONResponse:
        try:
            return JSONResponse(await AgentService.list())
        except Exception as exc:
            return cls._error_from_exception(exc)

    @classmethod
    async def _v1_list_permissions(cls, request: Request) -> JSONResponse:
        try:
            return JSONResponse(await PermissionService.list())
        except Exception as exc:
            return cls._error_from_exception(exc)

    @classmethod
    async def _v1_reply_permission(cls, request: Request) -> JSONResponse:
        request_id = request.path_params["id"]
        try:
            payload = await cls._json_payload(request, required=True)
            return JSONResponse(await PermissionService.reply(request_id, payload))
        except Exception as exc:
            return cls._error_from_exception(exc)

    @classmethod
    async def _v1_list_questions(cls, request: Request) -> JSONResponse:
        try:
            return JSONResponse(await QuestionService.list())
        except Exception as exc:
            return cls._error_from_exception(exc)

    @classmethod
    async def _v1_reply_question(cls, request: Request) -> JSONResponse:
        request_id = request.path_params["id"]
        try:
            payload = await cls._json_payload(request, required=True)
            return JSONResponse(await QuestionService.reply(request_id, payload))
        except Exception as exc:
            return cls._error_from_exception(exc)

    @classmethod
    async def _v1_reject_question(cls, request: Request) -> JSONResponse:
        request_id = request.path_params["id"]
        try:
            return JSONResponse(await QuestionService.reject(request_id))
        except Exception as exc:
            return cls._error_from_exception(exc)

    @classmethod
    async def _v1_event_stream(cls, request: Request) -> StreamingResponse:
        stream = EventService.stream()

        async def event_generator():
            try:
                async for event in stream:
                    yield cls._sse_data(event)
            except Exception as exc:
                yield cls._sse_data({"type": "error", "data": {"error": str(exc)}})

        return cls._sse_response(event_generator())

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
    async def _summarize_session(cls, request: Request) -> JSONResponse:
        """Manually compact a session."""
        session_id = request.path_params["session_id"]
        session = await Session.get(session_id)
        if not session:
            return JSONResponse(
                {"error": f"Session '{session_id}' not found"},
                status_code=404,
            )

        try:
            payload = await request.json()
        except Exception:
            payload = {}
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            return JSONResponse({"error": "Request body must be a JSON object"}, status_code=400)

        provider_id = payload.get("provider_id") or payload.get("providerID") or session.provider_id
        model_id = payload.get("model_id") or payload.get("modelID") or session.model_id
        auto = bool(payload.get("auto", False))

        if not provider_id or not model_id:
            provider_id, model_id = await Provider.default_model()

        provider_id = str(provider_id)
        model_id = str(model_id)

        try:
            await Provider.get_model(provider_id, model_id)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

        agent_name = session.agent or await Agent.default_agent()
        cwd = session.directory or str(Path.cwd())

        try:
            await SessionCompaction.create(
                session_id=session_id,
                agent=agent_name,
                provider_id=provider_id,
                model_id=model_id,
                auto=auto,
            )
            result = await SessionPrompt.loop(
                session_id=session_id,
                provider_id=provider_id,
                model_id=model_id,
                agent=agent_name,
                cwd=cwd,
                worktree=cwd,
                resume_history=True,
                auto_compaction=False,
            )
        except Exception as e:
            log.error("session summarize failed", {"session_id": session_id, "error": str(e)})
            return JSONResponse({"error": str(e)}, status_code=500)

        return JSONResponse(
            {
                "ok": result.result.error is None,
                "assistant_message_id": result.assistant_message_id,
                "status": result.result.status,
                "error": result.result.error,
            }
        )

    @classmethod
    async def _list_permissions(cls, request: Request) -> JSONResponse:
        """List pending permission requests."""
        from ..permission import Permission

        pending = await Permission.list_pending()
        return JSONResponse([item.model_dump() for item in pending])

    @classmethod
    async def _reply_permission(cls, request: Request) -> JSONResponse:
        """Reply to a permission request."""
        from ..permission import Permission, PermissionReply

        request_id = request.path_params["request_id"]
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            return JSONResponse({"error": "Request body must be a JSON object"}, status_code=400)

        reply_value = payload.get("reply")
        message = payload.get("message")
        if reply_value not in {r.value for r in PermissionReply}:
            return JSONResponse({"error": "Field 'reply' must be one of: once, always, reject"}, status_code=400)

        await Permission.reply(
            request_id=request_id,
            reply=PermissionReply(reply_value),
            message=message if isinstance(message, str) else None,
        )
        return JSONResponse(True)

    @classmethod
    async def _list_questions(cls, request: Request) -> JSONResponse:
        """List pending question requests."""
        from ..question import Question

        pending = await Question.list_pending()
        return JSONResponse([item.model_dump() for item in pending])

    @classmethod
    async def _reply_question(cls, request: Request) -> JSONResponse:
        """Reply to a question request."""
        from ..question import Question

        request_id = request.path_params["request_id"]
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            return JSONResponse({"error": "Request body must be a JSON object"}, status_code=400)

        answers = payload.get("answers")
        if not isinstance(answers, list) or any(not isinstance(item, list) for item in answers):
            return JSONResponse({"error": "Field 'answers' must be a list of string lists"}, status_code=400)
        if any(any(not isinstance(choice, str) for choice in item) for item in answers):
            return JSONResponse({"error": "Field 'answers' must contain only strings"}, status_code=400)

        await Question.reply(request_id, answers)
        return JSONResponse(True)

    @classmethod
    async def _reject_question(cls, request: Request) -> JSONResponse:
        """Reject a question request."""
        from ..question import Question

        request_id = request.path_params["request_id"]
        await Question.reject(request_id)
        return JSONResponse(True)

    @classmethod
    async def _event_stream(cls, request: Request) -> StreamingResponse:
        """Server-Sent Events stream for real-time updates."""
        async def event_generator():
            # Send initial connected event
            yield f"data: {json.dumps({'type': 'server.connected'})}\n\n"

            # Subscribe to bus events
            queue: asyncio.Queue = asyncio.Queue()

            def on_event(event: Any) -> None:
                if isinstance(event, dict):
                    payload = event
                elif hasattr(event, "model_dump"):
                    payload = event.model_dump()
                elif hasattr(event, "type") and hasattr(event, "properties"):
                    payload = {"type": event.type, "properties": event.properties}
                else:
                    payload = {"type": "server.event", "properties": {}}
                asyncio.create_task(queue.put(payload))

            unsubscribe = Bus.subscribe_all(on_event)

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
            finally:
                unsubscribe()

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
