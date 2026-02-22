"""Fetch remote web content."""

from __future__ import annotations

import base64
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal, Optional

import httpx
from pydantic import BaseModel, Field

from ..core.id import Identifier
from .tool import PermissionSpec, Tool, ToolContext, ToolResult

MAX_RESPONSE_SIZE = 5 * 1024 * 1024  # 5MB
DEFAULT_TIMEOUT_SECONDS = 30
MAX_TIMEOUT_SECONDS = 120


class WebFetchParams(BaseModel):
    """Parameters for webfetch."""

    url: str = Field(..., description="The URL to fetch content from")
    format: Literal["text", "markdown", "html"] = Field(
        "markdown",
        description="Output format",
    )
    timeout: Optional[int] = Field(None, description="Timeout in seconds (max 120)")


class _TextExtractor(HTMLParser):
    """Simple HTML text extractor."""

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs):  # type: ignore[override]
        if tag in {"script", "style", "noscript", "iframe", "object", "embed"}:
            self._skip_depth += 1
            return
        if self._skip_depth == 0 and tag in {"p", "div", "section", "article", "br", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str):  # type: ignore[override]
        if tag in {"script", "style", "noscript", "iframe", "object", "embed"} and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str):  # type: ignore[override]
        if self._skip_depth == 0:
            self.parts.append(data)

    def text(self) -> str:
        raw = "".join(self.parts)
        return re.sub(r"\n{3,}", "\n\n", raw).strip()


def _html_to_markdown(html: str) -> str:
    stripped = re.sub(r"<(script|style|noscript|iframe|object|embed)[^>]*>[\s\S]*?</\1>", "", html, flags=re.I)
    stripped = re.sub(r"<h1[^>]*>(.*?)</h1>", r"\n# \1\n", stripped, flags=re.I | re.S)
    stripped = re.sub(r"<h2[^>]*>(.*?)</h2>", r"\n## \1\n", stripped, flags=re.I | re.S)
    stripped = re.sub(r"<h3[^>]*>(.*?)</h3>", r"\n### \1\n", stripped, flags=re.I | re.S)
    stripped = re.sub(r"<li[^>]*>(.*?)</li>", r"\n- \1", stripped, flags=re.I | re.S)
    stripped = re.sub(r"<br\\s*/?>", "\n", stripped, flags=re.I)
    stripped = re.sub(r"</(p|div|section|article)>", "\n", stripped, flags=re.I)
    stripped = re.sub(r"<[^>]+>", "", stripped)
    stripped = re.sub(r"\n{3,}", "\n\n", stripped)
    return stripped.strip()


def _accept_header(fmt: str) -> str:
    if fmt == "markdown":
        return "text/markdown;q=1.0, text/x-markdown;q=0.9, text/plain;q=0.8, text/html;q=0.7, */*;q=0.1"
    if fmt == "text":
        return "text/plain;q=1.0, text/markdown;q=0.9, text/html;q=0.8, */*;q=0.1"
    if fmt == "html":
        return "text/html;q=1.0, application/xhtml+xml;q=0.9, text/plain;q=0.8, text/markdown;q=0.7, */*;q=0.1"
    return "*/*"


async def webfetch_execute(params: WebFetchParams, ctx: ToolContext) -> ToolResult:
    if not (params.url.startswith("http://") or params.url.startswith("https://")):
        raise ValueError("URL must start with http:// or https://")

    timeout_seconds = min(params.timeout or DEFAULT_TIMEOUT_SECONDS, MAX_TIMEOUT_SECONDS)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
        ),
        "Accept": _accept_header(params.format),
        "Accept-Language": "en-US,en;q=0.9",
    }

    async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True) as client:
        response = await client.get(params.url, headers=headers)
        if response.status_code == 403 and response.headers.get("cf-mitigated") == "challenge":
            headers["User-Agent"] = "opencode"
            response = await client.get(params.url, headers=headers)

    if response.status_code >= 400:
        raise RuntimeError(f"Request failed with status code: {response.status_code}")

    content_length = response.headers.get("content-length")
    if content_length and int(content_length) > MAX_RESPONSE_SIZE:
        raise RuntimeError("Response too large (exceeds 5MB limit)")

    body = response.content
    if len(body) > MAX_RESPONSE_SIZE:
        raise RuntimeError("Response too large (exceeds 5MB limit)")

    content_type = response.headers.get("content-type", "")
    mime = content_type.split(";")[0].strip().lower()
    title = f"{params.url} ({content_type or 'unknown'})"

    if mime.startswith("image/") and mime not in {"image/svg+xml", "image/vnd.fastbidsheet"}:
        encoded = base64.b64encode(body).decode("ascii")
        return ToolResult(
            title=title,
            output="Image fetched successfully",
            metadata={},
            attachments=[
                {
                    "id": Identifier.ascending("part"),
                    "session_id": ctx.session_id,
                    "message_id": ctx.message_id,
                    "type": "file",
                    "mime": mime,
                    "url": f"data:{mime};base64,{encoded}",
                }
            ],
        )

    text = response.text
    if params.format == "html":
        output = text
    elif params.format == "text":
        if "text/html" in content_type:
            parser = _TextExtractor()
            parser.feed(text)
            output = parser.text()
        else:
            output = text
    else:
        if "text/html" in content_type:
            output = _html_to_markdown(text)
        else:
            output = text

    return ToolResult(title=title, output=output, metadata={})


def webfetch_permissions(params: WebFetchParams, _ctx: ToolContext) -> list[PermissionSpec]:
    return [
        PermissionSpec(
            permission="webfetch",
            patterns=[params.url],
            always=["*"],
            metadata={
                "url": params.url,
                "format": params.format,
                "timeout": params.timeout,
            },
        )
    ]


_DESCRIPTION = (Path(__file__).parent / "webfetch.txt").read_text(encoding="utf-8")

WebFetchTool = Tool.define(
    tool_id="webfetch",
    description=_DESCRIPTION,
    parameters_type=WebFetchParams,
    permission_fn=webfetch_permissions,
    execute_fn=webfetch_execute,
    auto_truncate=True,
)
