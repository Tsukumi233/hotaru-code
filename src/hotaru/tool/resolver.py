"""Tool resolution utilities shared by session orchestration layers."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from ..util.log import Log
from .registry import ToolRegistry
from .schema import strictify_schema

log = Log.create({"service": "tool.resolver"})


class ToolResolver:
    """Resolve effective tool definitions for a turn."""

    @classmethod
    async def resolve(
        cls,
        *,
        caller_agent: Optional[str],
        provider_id: Optional[str],
        model_id: Optional[str],
        permission_rules: Optional[List[Dict[str, Any]]] = None,
        include_mcp: bool = True,
    ) -> List[Dict[str, Any]]:
        tools = await ToolRegistry.get_tool_definitions(
            caller_agent=caller_agent,
            provider_id=provider_id,
            model_id=model_id,
        )
        if include_mcp:
            tools.extend(await cls._mcp_tools())
        if permission_rules:
            return cls._filter_disabled_tools(tools, permission_rules)
        return tools

    @classmethod
    async def _mcp_tools(cls) -> List[Dict[str, Any]]:
        mcp_tools = await cls._mcp_map()
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

    @classmethod
    async def mcp_info(
        cls,
        tool_id: str,
    ) -> Optional[Dict[str, Any]]:
        return (await cls._mcp_map()).get(tool_id)

    @classmethod
    async def _mcp_map(cls) -> Dict[str, Dict[str, Any]]:
        try:
            from ..mcp import MCP

            return await MCP.tools()
        except asyncio.CancelledError as e:
            task = asyncio.current_task()
            if task and task.cancelling():
                raise
            log.warn("failed to load MCP tools", {"error": str(e)})
            return {}
        except Exception as e:
            log.warn("failed to load MCP tools", {"error": str(e)})
            return {}

    @classmethod
    def _filter_disabled_tools(
        cls,
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
