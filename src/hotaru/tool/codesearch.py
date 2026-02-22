"""Exa-based code context search tool."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import httpx
from pydantic import BaseModel, Field

from .tool import PermissionSpec, Tool, ToolContext, ToolResult

API_URL = "https://mcp.exa.ai/mcp"


class CodeSearchParams(BaseModel):
    """Parameters for codesearch."""

    query: str = Field(..., description="Query for API/library code context")
    tokensNum: Optional[int] = Field(5000, ge=1000, le=50000, description="Token budget")


def _extract_sse_text(payload: str) -> Optional[str]:
    for line in payload.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            data = json.loads(line[6:])
        except Exception:
            continue
        content = (((data or {}).get("result") or {}).get("content") or [])
        if content and isinstance(content[0], dict) and isinstance(content[0].get("text"), str):
            return content[0]["text"]
    return None


async def codesearch_execute(params: CodeSearchParams, ctx: ToolContext) -> ToolResult:
    del ctx

    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "get_code_context_exa",
            "arguments": {
                "query": params.query,
                "tokensNum": params.tokensNum or 5000,
            },
        },
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        response = await client.post(
            API_URL,
            json=body,
            headers={
                "accept": "application/json, text/event-stream",
                "content-type": "application/json",
            },
        )
    if response.status_code >= 400:
        raise RuntimeError(f"Code search error ({response.status_code}): {response.text}")

    text = _extract_sse_text(response.text)
    if text is None:
        text = (
            "No code snippets or documentation found. "
            "Try a more specific query or verify library/framework names."
        )
    return ToolResult(
        title=f"Code search: {params.query}",
        output=text,
        metadata={},
    )


def codesearch_permissions(params: CodeSearchParams, _ctx: ToolContext) -> list[PermissionSpec]:
    return [
        PermissionSpec(
            permission="codesearch",
            patterns=[params.query],
            always=["*"],
            metadata=params.model_dump(exclude_none=True),
        )
    ]


_DESCRIPTION = (Path(__file__).parent / "codesearch.txt").read_text(encoding="utf-8")

CodeSearchTool = Tool.define(
    tool_id="codesearch",
    description=_DESCRIPTION,
    parameters_type=CodeSearchParams,
    permission_fn=codesearch_permissions,
    execute_fn=codesearch_execute,
    auto_truncate=True,
)
