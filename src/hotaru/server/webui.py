"""Helpers for serving packaged WebUI assets."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi.responses import FileResponse, HTMLResponse


def web_dist_candidates() -> list[Path]:
    out: list[Path] = []
    custom = str(os.getenv("HOTARU_WEB_DIST") or "").strip()
    if custom:
        out.append(Path(custom))

    here = Path(__file__).resolve()
    if len(here.parents) >= 2:
        out.append(here.parents[1] / "webui" / "dist")
    return out


def web_dist_path() -> Path | None:
    for path in web_dist_candidates():
        if (path / "index.html").is_file():
            return path
    return None


def web_index_response() -> FileResponse | HTMLResponse:
    dist = web_dist_path()
    if dist is None:
        return HTMLResponse(
            "<!doctype html><html><body><h1>Hotaru WebUI is not built.</h1></body></html>",
            status_code=200,
        )
    return FileResponse(dist / "index.html")


def web_asset_path(path: str) -> Path | None:
    dist = web_dist_path()
    if dist is None:
        return None

    raw = str(path or "").strip("/")
    if not raw:
        return None

    rel = Path(raw)
    if any(part == ".." for part in rel.parts):
        return None

    root = dist.resolve()
    target = (dist / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None

    if not target.is_file():
        return None
    return target
