"""Batch tool for parallel local tool execution."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from ..core.id import Identifier
from .tool import Tool, ToolContext, ToolResult

DISALLOWED = {"batch"}
FILTERED_FROM_SUGGESTIONS = {"invalid", "patch", *DISALLOWED}
MAX_CALLS = 25


class BatchCall(BaseModel):
    """Single batched tool call."""

    tool: str = Field(..., description="Tool name")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Tool parameters")


class BatchParams(BaseModel):
    """Parameters for batch execution."""

    tool_calls: List[BatchCall] = Field(..., description="Array of tool calls to execute in parallel")


def _clone_context(ctx: ToolContext, call_id: str) -> ToolContext:
    return ToolContext(
        session_id=ctx.session_id,
        message_id=ctx.message_id,
        agent=ctx.agent,
        call_id=call_id,
        extra=dict(ctx.extra),
        _metadata=dict(ctx._metadata),
        _aborted=ctx._aborted,
        _ruleset=list(ctx._ruleset),
        messages=list(ctx.messages),
    )


async def batch_execute(params: BatchParams, ctx: ToolContext) -> ToolResult:
    from .registry import ToolRegistry

    calls = params.tool_calls[:MAX_CALLS]
    discarded = params.tool_calls[MAX_CALLS:]
    tool_map = {tool.id: tool for tool in ToolRegistry.list()}

    async def _run(call: BatchCall) -> Dict[str, Any]:
        if call.tool in DISALLOWED:
            return {"success": False, "tool": call.tool, "error": f"Tool '{call.tool}' is not allowed in batch."}

        tool = tool_map.get(call.tool)
        if tool is None:
            names = [name for name in tool_map if name not in FILTERED_FROM_SUGGESTIONS]
            return {
                "success": False,
                "tool": call.tool,
                "error": (
                    f"Tool '{call.tool}' not in registry. External tools cannot be batched. "
                    f"Available tools: {', '.join(names)}"
                ),
            }

        try:
            args = tool.parameters_type.model_validate(call.parameters)
            result = await tool.execute(args, _clone_context(ctx, Identifier.ascending("call")))
            return {"success": True, "tool": call.tool, "result": result}
        except Exception as exc:
            return {"success": False, "tool": call.tool, "error": str(exc)}

    results = await asyncio.gather(*[_run(call) for call in calls])
    for call in discarded:
        results.append(
            {
                "success": False,
                "tool": call.tool,
                "error": f"Maximum of {MAX_CALLS} tools allowed in batch",
            }
        )

    successful = len([row for row in results if row.get("success")])
    failed = len(results) - successful
    if failed > 0:
        output = f"Executed {successful}/{len(results)} tools successfully. {failed} failed."
    else:
        output = f"All {successful} tools executed successfully.\n\nKeep using the batch tool for optimal performance."

    attachments = []
    for row in results:
        if row.get("success"):
            attachments.extend(row["result"].attachments)

    return ToolResult(
        title=f"Batch execution ({successful}/{len(results)} successful)",
        output=output,
        attachments=attachments,
        metadata={
            "totalCalls": len(results),
            "successful": successful,
            "failed": failed,
            "tools": [call.tool for call in params.tool_calls],
            "details": [
                {
                    "tool": row.get("tool"),
                    "success": bool(row.get("success")),
                    "error": row.get("error"),
                }
                for row in results
            ],
        },
    )


_DESCRIPTION = (Path(__file__).parent / "batch.txt").read_text(encoding="utf-8")

BatchTool = Tool.define(
    tool_id="batch",
    description=_DESCRIPTION,
    parameters_type=BatchParams,
    execute_fn=batch_execute,
    auto_truncate=False,
)
