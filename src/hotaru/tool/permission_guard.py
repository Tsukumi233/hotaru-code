"""Permission guard for unified tool execution checks."""

from __future__ import annotations

from .tool import PermissionSpec, ToolContext


class PermissionGuard:
    """Apply pre-execution permission checks."""

    @staticmethod
    async def check(specs: list[PermissionSpec], ctx: ToolContext) -> None:
        for spec in specs:
            if not spec.patterns:
                continue
            await ctx.ask(
                permission=spec.permission,
                patterns=list(spec.patterns),
                always=list(spec.always) if spec.always else None,
                metadata=dict(spec.metadata) if spec.metadata else None,
            )
