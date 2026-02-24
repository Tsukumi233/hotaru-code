"""FastAPI dependencies shared across transport handlers."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote

from fastapi import Request

from ..project import use_runtime
from ..runtime import AppContext
from ..util.log import Log

log = Log.create({"service": "server.deps"})


def decode_directory_value(value: str | None) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    try:
        return unquote(text)
    except Exception:
        return text


def resolve_request_directory(request: Request) -> str:
    from_state = getattr(request.state, "request_directory", None)
    if isinstance(from_state, str) and from_state.strip():
        return from_state

    for source, value in (
        ("header", request.headers.get("x-hotaru-directory")),
        ("query", request.query_params.get("directory")),
    ):
        resolved = decode_directory_value(value)
        if resolved:
            log.debug("resolved request directory", {"source": source, "directory": resolved})
            return resolved

    fallback = str(Path.cwd())
    log.debug("resolved request directory", {"source": "cwd", "directory": fallback})
    return fallback


def resolve_app_context(request: Request) -> AppContext:
    try:
        return use_runtime()
    except RuntimeError as exc:
        raise RuntimeError("Application context is not initialized") from exc
