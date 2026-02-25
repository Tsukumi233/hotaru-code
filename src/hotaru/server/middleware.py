"""Pure ASGI middleware classes for the Hotaru server."""

from __future__ import annotations

import secrets
import time
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, unquote

from ..core.bus import Bus
from ..project import instance_bootstrap, run_in_instance
from ..runtime import AppContext
from ..util.log import Log

Scope = dict
Receive = Callable
Send = Callable
Message = dict

access = Log.create({"service": "server.access"})


def _header(scope: Scope, name: bytes) -> str | None:
    for key, val in scope.get("headers", []):
        if key == name:
            return val.decode("latin-1")
    return None


def _client_ip(scope: Scope) -> str | None:
    client = scope.get("client")
    return client[0] if client else None


class AccessLogMiddleware:
    """Generates request IDs, logs access, injects X-Request-ID header."""

    def __init__(self, app: Callable, enabled: bool = True) -> None:
        self.app = app
        self.enabled = enabled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        rid = _header(scope, b"x-request-id") or secrets.token_hex(8)
        scope.setdefault("state", {})["request_id"] = rid

        path = scope.get("path", "")
        method = scope.get("method", "")
        query = (scope.get("query_string") or b"").decode("latin-1") or None
        begin = time.perf_counter()
        status = 500

        async def inject(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", rid.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, inject)
        except Exception as exc:
            if self.enabled:
                access.error("request failed", {
                    "request_id": rid,
                    "method": method,
                    "path": path,
                    "query": query,
                    "client_ip": _client_ip(scope),
                    "duration_ms": int((time.perf_counter() - begin) * 1000),
                    "error": str(exc),
                })
            raise

        if not self.enabled:
            return
        access.info("request", {
            "request_id": rid,
            "method": method,
            "path": path,
            "query": query,
            "status": status,
            "client_ip": _client_ip(scope),
            "duration_ms": int((time.perf_counter() - begin) * 1000),
        })


def _resolve_directory(scope: Scope) -> str:
    """Extract directory from ASGI scope headers/query, matching deps.resolve_request_directory."""
    header = _header(scope, b"x-hotaru-directory")
    if header:
        decoded = unquote(header.strip())
        if decoded:
            return decoded

    qs = parse_qs((scope.get("query_string") or b"").decode("latin-1"))
    values = qs.get("directory", [])
    if values:
        decoded = unquote(values[0].strip())
        if decoded:
            return decoded

    return str(Path.cwd())


class RequestContextMiddleware:
    """Sets up Bus context and project instance scope for /v1/ requests."""

    def __init__(self, app: Callable, ctx: AppContext) -> None:
        self.app = app
        self.ctx = ctx

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        token = Bus.provide(self.ctx.bus)
        try:
            path = scope.get("path", "")
            if not path.startswith("/v1/"):
                await self.app(scope, receive, send)
                return

            directory = _resolve_directory(scope)
            scope.setdefault("state", {})["request_directory"] = directory

            async def dispatch() -> None:
                await self.app(scope, receive, send)

            async def init() -> None:
                await instance_bootstrap(app=self.ctx)

            await run_in_instance(directory=directory, fn=dispatch, init=init)
        finally:
            Bus.restore(token)
