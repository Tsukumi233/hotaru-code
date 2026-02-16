"""Exa-based web search tool."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Optional

import httpx
from pydantic import BaseModel, Field

from .tool import Tool, ToolContext, ToolResult

API_URL = "https://mcp.exa.ai/mcp"
DEFAULT_RESULTS = 8


class WebSearchParams(BaseModel):
    """Parameters for websearch."""

    query: str = Field(..., description="Websearch query")
    numResults: Optional[int] = Field(None, description="Number of search results to return (default: 8)")
    livecrawl: Optional[Literal["fallback", "preferred"]] = Field(None, description="Live crawl mode")
    type: Optional[Literal["auto", "fast", "deep"]] = Field(None, description="Search type")
    contextMaxCharacters: Optional[int] = Field(None, description="Context max chars")


def _extract_sse_text(payload: str) -> Optional[str]:
    for line in payload.splitlines():
        if not line.startswith("data: "):
            continue
        raw = line[6:]
        try:
            data = json.loads(raw)
        except Exception:
            continue
        content = (((data or {}).get("result") or {}).get("content") or [])
        if content and isinstance(content[0], dict) and isinstance(content[0].get("text"), str):
            return content[0]["text"]
    return None


async def websearch_execute(params: WebSearchParams, ctx: ToolContext) -> ToolResult:
    await ctx.ask(
        permission="websearch",
        patterns=[params.query],
        always=["*"],
        metadata=params.model_dump(exclude_none=True),
    )

    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "web_search_exa",
            "arguments": {
                "query": params.query,
                "type": params.type or "auto",
                "numResults": params.numResults or DEFAULT_RESULTS,
                "livecrawl": params.livecrawl or "fallback",
                "contextMaxCharacters": params.contextMaxCharacters,
            },
        },
    }

    timeout = httpx.Timeout(25.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            API_URL,
            json=body,
            headers={
                "accept": "application/json, text/event-stream",
                "content-type": "application/json",
            },
        )
    if response.status_code >= 400:
        raise RuntimeError(f"Search error ({response.status_code}): {response.text}")

    text = _extract_sse_text(response.text)
    if text is None:
        text = "No search results found. Please try a different query."
    return ToolResult(
        title=f"Web search: {params.query}",
        output=text,
        metadata={},
    )


_DESCRIPTION = (Path(__file__).parent / "websearch.txt").read_text(encoding="utf-8")

WebSearchTool = Tool.define(
    tool_id="websearch",
    description=_DESCRIPTION,
    parameters_type=WebSearchParams,
    execute_fn=websearch_execute,
    auto_truncate=True,
)

