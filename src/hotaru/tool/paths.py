"""Shared path resolution utilities for tool implementations."""

from pathlib import Path

from .tool import ToolContext


def resolve(path: str | Path, ctx: ToolContext) -> Path:
    """Resolve a path relative to the context cwd.

    If *path* is already absolute it is returned as-is; otherwise it is
    joined against ``ctx.cwd``.
    """
    cwd = Path(ctx.cwd or str(Path.cwd()))
    p = Path(path)
    if p.is_absolute():
        return p
    return cwd / p


def resolve_or_cwd(path: str | Path | None, ctx: ToolContext) -> Path:
    """Resolve a path, falling back to cwd when *path* is ``None``."""
    if path is None:
        return Path(ctx.cwd or str(Path.cwd()))
    return resolve(path, ctx)
