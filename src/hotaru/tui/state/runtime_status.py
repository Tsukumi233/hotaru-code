"""Shared runtime status view model for TUI surfaces.

This module centralizes the shape used by footer/status UI so
all surfaces render from the same snapshot.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class RuntimeStatusSnapshot:
    """Normalized runtime status snapshot for TUI rendering."""

    mcp: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    lsp: List[Dict[str, Any]] = field(default_factory=list)
    mcp_connected: int = 0
    mcp_error: bool = False
    lsp_count: int = 0
    permission_count: int = 0
    show_status_hint: bool = False
