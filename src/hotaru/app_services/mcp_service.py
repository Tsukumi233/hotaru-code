"""MCP application service."""

from __future__ import annotations

from typing import Any

from ..runtime import AppContext


class McpService:
    """Thin orchestration for MCP operations."""

    @classmethod
    async def status(cls, app: AppContext) -> dict[str, dict[str, Any]]:
        status = await app.mcp.status()
        return {name: value.model_dump() for name, value in status.items()}

    @classmethod
    async def connect(cls, app: AppContext, name: str) -> dict[str, bool]:
        await app.mcp.connect(name, use_oauth=True)
        return {"ok": True}

    @classmethod
    async def disconnect(cls, app: AppContext, name: str) -> dict[str, bool]:
        await app.mcp.disconnect(name)
        return {"ok": True}

    @classmethod
    async def auth_start(cls, app: AppContext, name: str) -> dict[str, str]:
        if not await app.mcp.supports_oauth(name):
            raise ValueError(f"MCP server {name} does not support OAuth")
        return await app.mcp.start_auth(name)

    @classmethod
    async def auth_callback(
        cls,
        app: AppContext,
        name: str,
        code: str,
        state: str,
    ) -> dict[str, Any]:
        status = await app.mcp.finish_auth(name, code=code, state=state)
        return status.model_dump()

    @classmethod
    async def auth_authenticate(cls, app: AppContext, name: str) -> dict[str, Any]:
        if not await app.mcp.supports_oauth(name):
            raise ValueError(f"MCP server {name} does not support OAuth")
        status = await app.mcp.authenticate(name)
        return status.model_dump()

    @classmethod
    async def auth_remove(cls, app: AppContext, name: str) -> dict[str, bool]:
        await app.mcp.remove_auth(name)
        return {"ok": True}
