"""Project-instance bootstrap hooks.

Runs per-instance subsystem initialization after the runtime is bound.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .runtime_scope import bind_runtime

if TYPE_CHECKING:
    from ..runtime import AppContext


async def instance_bootstrap(*, app: AppContext) -> None:
    """Initialize per-instance runtime bindings and subsystems."""
    bind_runtime(app)
