"""Tool execution orchestration for session processor."""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set

from ..core.id import Identifier
from ..permission import CorrectedError, DeniedError, RejectedError
from ..question.question import RejectedError as QuestionRejectedError
from ..tool import ToolContext
from ..tool.registry import ToolRegistry
from ..tool.resolver import ToolResolver
from ..util.log import Log
from .doom_loop import DoomLoopDetector
from .processor_types import ToolCallState

log = Log.create({"service": "session.tool_executor"})

_STRUCTURED_OUTPUT_TOOL = "StructuredOutput"


class ToolExecutor:
    """Execute built-in and MCP tools with permissions and metadata."""

    def __init__(
        self,
        *,
        session_id: str,
        model_id: str,
        provider_id: str,
        cwd: str,
        worktree: str,
        doom: DoomLoopDetector,
        emit_tool_update: Callable[[Optional[callable], ToolCallState], Awaitable[None]],
        execute_mcp: Optional[Callable[..., Awaitable[Dict[str, Any]]]] = None,
    ) -> None:
        self.session_id = session_id
        self.model_id = model_id
        self.provider_id = provider_id
        self.cwd = cwd
        self.worktree = worktree
        self.doom = doom
        self.emit_tool_update = emit_tool_update
        self.execute_mcp = execute_mcp
        self._structured_output: Optional[Any] = None

    def reset_turn(self) -> None:
        self._structured_output = None

    @property
    def structured_output(self) -> Optional[Any]:
        return self._structured_output

    async def execute(
        self,
        *,
        tool_name: str,
        tool_input: Dict[str, Any],
        allowed_tools: Optional[Set[str]],
        messages: List[Dict[str, Any]],
        agent: str,
        tc: Optional[ToolCallState] = None,
        on_tool_update: Optional[callable] = None,
        assistant_message_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if allowed_tools is not None and tool_name not in allowed_tools:
            return {"error": f"Unknown tool: {tool_name}"}

        if tool_name == _STRUCTURED_OUTPUT_TOOL:
            if not allowed_tools or tool_name not in allowed_tools:
                return {"error": f"Unknown tool: {tool_name}"}
            self._structured_output = dict(tool_input or {})
            return {
                "output": "Structured output captured successfully.",
                "title": "Structured Output",
                "metadata": {"valid": True},
            }

        tool = ToolRegistry.get(tool_name)
        if not tool:
            mcp_info = await ToolResolver.mcp_info(tool_name)
            if mcp_info:
                if self.execute_mcp:
                    return await self.execute_mcp(
                        tool_id=tool_name,
                        mcp_info=mcp_info,
                        tool_input=tool_input,
                    )
                return await self.execute_mcp_tool(
                    tool_id=tool_name,
                    mcp_info=mcp_info,
                    tool_input=tool_input,
                )
            return {"error": f"Unknown tool: {tool_name}"}

        merged_ruleset: List[Dict[str, Any]] = []
        try:
            from ..agent import Agent
            from .session import Session

            agent_info = await Agent.get(agent)
            if agent_info and agent_info.permission:
                merged_ruleset.extend(agent_info.permission)

            session = await Session.get(self.session_id)
            session_permission = getattr(session, "permission", None) if session else None
            if isinstance(session_permission, list):
                merged_ruleset.extend(session_permission)
        except Exception as e:
            log.warn("failed to load agent permissions", {"error": str(e)})

        pending_tasks: List[asyncio.Task[Any]] = []

        def _handle_metadata_update(snapshot: Dict[str, Any]) -> None:
            if tc is None:
                return
            title = snapshot.get("title")
            tc.title = str(title) if isinstance(title, str) and title else tc.title
            tc.metadata = {key: value for key, value in snapshot.items() if key != "title"}
            if on_tool_update:
                pending_tasks.append(asyncio.create_task(self.emit_tool_update(on_tool_update, tc)))

        try:
            await self.doom.check(tool_name=tool_name, tool_input=tool_input, ruleset=merged_ruleset)

            ctx = ToolContext(
                session_id=self.session_id,
                message_id=assistant_message_id or Identifier.ascending("message"),
                agent=agent,
                call_id=(tc.id if tc and tc.id else Identifier.ascending("call")),
                extra={
                    "cwd": self.cwd,
                    "worktree": self.worktree,
                    "provider_id": self.provider_id,
                    "model_id": self.model_id,
                },
                messages=list(messages),
                _on_metadata=_handle_metadata_update,
                _ruleset=merged_ruleset,
            )

            result = await ToolRegistry.execute(tool_name, tool_input, ctx)
            if pending_tasks:
                await asyncio.gather(*pending_tasks, return_exceptions=True)

            raw_metadata = dict(ctx._metadata or {})
            raw_metadata.update(dict(result.metadata or {}))
            title = str(result.title or raw_metadata.pop("title", "") or "")
            if title:
                raw_metadata["title"] = title

            return {
                "output": result.output,
                "title": title,
                "metadata": raw_metadata,
                "attachments": result.attachments,
            }

        except (RejectedError, CorrectedError) as e:
            if pending_tasks:
                await asyncio.gather(*pending_tasks, return_exceptions=True)
            log.info("permission error", {"tool": tool_name, "error": str(e)})
            return {"error": str(e), "blocked": True}
        except DeniedError as e:
            if pending_tasks:
                await asyncio.gather(*pending_tasks, return_exceptions=True)
            log.info("permission denied by ruleset", {"tool": tool_name, "error": str(e)})
            return {"error": str(e)}
        except QuestionRejectedError as e:
            if pending_tasks:
                await asyncio.gather(*pending_tasks, return_exceptions=True)
            log.info("question rejected", {"tool": tool_name, "error": str(e)})
            return {"error": str(e), "blocked": True}
        except Exception as e:
            if pending_tasks:
                await asyncio.gather(*pending_tasks, return_exceptions=True)
            log.error("tool execution error", {"tool": tool_name, "error": str(e)})
            return {"error": str(e)}

    async def execute_mcp_tool(
        self,
        *,
        tool_id: str,
        mcp_info: Dict[str, Any],
        tool_input: Dict[str, Any],
    ) -> Dict[str, Any]:
        from ..mcp import MCP

        client_name = mcp_info["client"]
        original_name = mcp_info["name"]

        state = await MCP._get_state()
        client = state.clients.get(client_name)
        if not client:
            return {"error": f"MCP client not connected: {client_name}"}

        try:
            timeout = mcp_info.get("timeout", 30.0)
            result = await asyncio.wait_for(client.call_tool(original_name, tool_input), timeout=timeout)

            text_parts = []
            for content in (result.content or []):
                if hasattr(content, "text"):
                    text_parts.append(content.text)

            return {
                "output": "\n".join(text_parts) or "Tool completed",
                "title": "",
                "metadata": {},
            }
        except asyncio.TimeoutError:
            return {"error": f"MCP tool call timed out: {original_name}"}
        except Exception as e:
            log.error(
                "MCP tool execution error",
                {
                    "tool": original_name,
                    "client": client_name,
                    "error": str(e),
                },
            )
            return {"error": str(e)}
