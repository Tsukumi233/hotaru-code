"""Helpers for external directory permission checks."""

from pathlib import Path
from typing import Optional

from .tool import PermissionSpec, ToolContext


def _contains_path(base: Path, target: Path) -> bool:
    try:
        target.relative_to(base)
        return True
    except ValueError:
        return False


async def assert_external_directory(
    ctx: ToolContext,
    target: Optional[Path],
    kind: str = "file",
    bypass: bool = False,
) -> list[PermissionSpec]:
    """Build external_directory permission spec when target is outside project bounds."""
    if target is None or bypass:
        return []

    cwd_value = ctx.cwd or str(Path.cwd())
    worktree_value = ctx.worktree

    cwd = Path(cwd_value).resolve()
    target_path = target if target.is_absolute() else (cwd / target)
    target_path = target_path.resolve()

    if _contains_path(cwd, target_path):
        return []

    if worktree_value and worktree_value != "/":
        worktree = Path(worktree_value).resolve()
        if _contains_path(worktree, target_path):
            return []

    parent_dir = target_path if kind == "directory" else target_path.parent
    glob = str(parent_dir / "*")

    return [
        PermissionSpec(
            permission="external_directory",
            patterns=[glob],
            always=[glob],
            metadata={
                "directory": str(parent_dir),
                "filepath": str(target_path),
            },
        )
    ]
