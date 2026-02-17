"""Selectors that derive TUI-friendly view models from contexts."""

from __future__ import annotations

from typing import Optional

from .runtime_status import RuntimeStatusSnapshot


def _connected_mcp_count(mcp: dict) -> int:
    return sum(1 for value in mcp.values() if isinstance(value, dict) and value.get("status") == "connected")


def _has_mcp_error(mcp: dict) -> bool:
    return any(isinstance(value, dict) and value.get("status") == "failed" for value in mcp.values())


def select_runtime_status(*, sync, route: Optional[object] = None) -> RuntimeStatusSnapshot:
    """Build a normalized runtime status snapshot for UI rendering."""
    mcp = sync.data.mcp if isinstance(sync.data.mcp, dict) else {}
    lsp = sync.data.lsp if isinstance(sync.data.lsp, list) else []

    permission_count = 0
    if route is not None and getattr(route, "is_session", None) and route.is_session():
        session_id = route.get_session_id()
        if isinstance(session_id, str) and session_id:
            permission_count = len(sync.get_permissions(session_id))

    mcp_connected = _connected_mcp_count(mcp)
    mcp_error = _has_mcp_error(mcp)
    lsp_count = len(lsp)
    show_status_hint = any((mcp_connected > 0, mcp_error, lsp_count > 0, permission_count > 0))

    return RuntimeStatusSnapshot(
        mcp=mcp,
        lsp=lsp,
        mcp_connected=mcp_connected,
        mcp_error=mcp_error,
        lsp_count=lsp_count,
        permission_count=permission_count,
        show_status_hint=show_status_hint,
    )
