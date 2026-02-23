"""Tool resolution utilities shared by session orchestration layers."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ..util.log import Log
from .schema import strictify_schema

if TYPE_CHECKING:
    from ..runtime import AppContext

log = Log.create({"service": "tool.resolver"})


class ToolResolver:
    """Resolve effective tool definitions for a turn."""

    def __init__(self, *, app: AppContext) -> None:
        self.app = app

    def _mcp_available(self) -> bool:
        return self.app.subsystem_ready("mcp")

    async def resolve(
        self,
        *,
        caller_agent: Optional[str],
        provider_id: Optional[str],
        model_id: Optional[str],
        permission_rules: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        tools = await self.app.tools.get_tool_definitions(
            app=self.app,
            caller_agent=caller_agent,
            provider_id=provider_id,
            model_id=model_id,
        )
        if self._mcp_available():
            tools.extend(await self._mcp_tools())
        if permission_rules:
            return self._filter_disabled_tools(tools, permission_rules)
        return tools

    async def _mcp_tools(self) -> List[Dict[str, Any]]:
        mcp_tools = await self._mcp_map()
        return [
            {
                "type": "function",
                "function": {
                    "name": tool_id,
                    "description": tool_info.get("description", ""),
                    "parameters": strictify_schema(
                        {"type": "object", **dict(tool_info.get("input_schema") or {})}
                    ),
                },
            }
            for tool_id, tool_info in mcp_tools.items()
        ]

    async def mcp_info(
        self,
        tool_id: str,
    ) -> Optional[Dict[str, Any]]:
        if not self._mcp_available():
            return None
        return (await self._mcp_map()).get(tool_id)

    async def _mcp_map(self) -> Dict[str, Dict[str, Any]]:
        try:
            return await self.app.mcp.tools()
        except asyncio.CancelledError as e:
            task = asyncio.current_task()
            if task and task.cancelling():
                raise
            log.warn("failed to load MCP tools", {"error": str(e)})
            return {}
        except Exception as e:
            log.warn("failed to load MCP tools", {"error": str(e)})
            return {}

    def _filter_disabled_tools(
        self,
        tools: List[Dict[str, Any]],
        rules: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        try:
            from ..permission import Permission

            ruleset = Permission.from_config_list(rules)
            names = [
                str(item.get("function", {}).get("name"))
                for item in tools
                if isinstance(item, dict) and isinstance(item.get("function"), dict)
            ]
            disabled = Permission.disabled_tools(names, ruleset)
            if not disabled:
                return tools
            log.info("filtering disabled tools", {"disabled": list(disabled)})
            return [item for item in tools if item.get("function", {}).get("name") not in disabled]
        except Exception as e:
            log.warn("failed to filter disabled tools", {"error": str(e)})
            return tools
