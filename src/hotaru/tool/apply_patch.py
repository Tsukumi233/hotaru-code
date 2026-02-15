"""apply_patch-compatible tool."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from ..patch import (
    AddHunk,
    DeleteHunk,
    PatchParseError,
    UpdateHunk,
    create_unified_diff,
    derive_new_contents_from_chunks,
    parse_patch,
)
from .edit import trim_diff
from .external_directory import assert_external_directory
from .lsp_feedback import append_lsp_error_feedback
from .tool import Tool, ToolContext, ToolResult


class ApplyPatchParams(BaseModel):
    """Parameters for apply_patch."""

    patch_text: str = Field(..., alias="patchText", description="Full patch text to apply")

    model_config = ConfigDict(populate_by_name=True)


@dataclass
class _FileChange:
    file_path: Path
    old_content: str
    new_content: str
    change_type: str
    diff: str
    move_path: Optional[Path] = None
    additions: int = 0
    deletions: int = 0


def _line_stats(old: str, new: str) -> tuple[int, int]:
    old_count = len([line for line in old.splitlines() if line.strip() != ""])
    new_count = len([line for line in new.splitlines() if line.strip() != ""])
    additions = max(0, new_count - old_count)
    deletions = max(0, old_count - new_count)
    return additions, deletions


async def _build_changes(params: ApplyPatchParams, ctx: ToolContext) -> List[_FileChange]:
    cwd = Path(str(ctx.extra.get("cwd") or Path.cwd()))
    hunks = parse_patch(params.patch_text)
    if not hunks:
        raise PatchParseError("apply_patch verification failed: no hunks found")

    changes: List[_FileChange] = []
    for hunk in hunks:
        file_path = (cwd / hunk.path).resolve()
        await assert_external_directory(ctx, file_path)

        if isinstance(hunk, AddHunk):
            old = ""
            new = hunk.contents if hunk.contents.endswith("\n") or not hunk.contents else f"{hunk.contents}\n"
            diff = trim_diff(create_unified_diff(str(file_path), old, new))
            adds, dels = _line_stats(old, new)
            changes.append(
                _FileChange(
                    file_path=file_path,
                    old_content=old,
                    new_content=new,
                    change_type="add",
                    diff=diff,
                    additions=adds,
                    deletions=dels,
                )
            )
            continue

        if isinstance(hunk, DeleteHunk):
            if not file_path.exists() or file_path.is_dir():
                raise FileNotFoundError(f"apply_patch verification failed: cannot delete missing file {file_path}")
            old = file_path.read_text(encoding="utf-8")
            diff = trim_diff(create_unified_diff(str(file_path), old, ""))
            adds, dels = _line_stats(old, "")
            changes.append(
                _FileChange(
                    file_path=file_path,
                    old_content=old,
                    new_content="",
                    change_type="delete",
                    diff=diff,
                    additions=adds,
                    deletions=dels,
                )
            )
            continue

        if isinstance(hunk, UpdateHunk):
            if not file_path.exists() or file_path.is_dir():
                raise FileNotFoundError(f"apply_patch verification failed: failed to read file to update: {file_path}")
            old = file_path.read_text(encoding="utf-8")
            new = derive_new_contents_from_chunks(str(file_path), hunk.chunks, old)
            diff = trim_diff(create_unified_diff(str(file_path), old, new))
            move_path = (cwd / hunk.move_path).resolve() if hunk.move_path else None
            if move_path is not None:
                await assert_external_directory(ctx, move_path)
            adds, dels = _line_stats(old, new)
            changes.append(
                _FileChange(
                    file_path=file_path,
                    old_content=old,
                    new_content=new,
                    change_type="move" if move_path else "update",
                    move_path=move_path,
                    diff=diff,
                    additions=adds,
                    deletions=dels,
                )
            )
            continue

    return changes


async def apply_patch_execute(params: ApplyPatchParams, ctx: ToolContext) -> ToolResult:
    if not params.patch_text.strip():
        raise ValueError("patchText is required")

    try:
        changes = await _build_changes(params, ctx)
    except PatchParseError as exc:
        raise RuntimeError(f"apply_patch verification failed: {exc}") from exc

    total_diff = "\n".join(change.diff for change in changes if change.diff)
    files_metadata = [
        {
            "filePath": str(change.file_path),
            "relativePath": str(change.move_path or change.file_path),
            "type": change.change_type,
            "diff": change.diff,
            "before": change.old_content,
            "after": change.new_content,
            "additions": change.additions,
            "deletions": change.deletions,
            "movePath": str(change.move_path) if change.move_path else None,
        }
        for change in changes
    ]

    await ctx.ask(
        permission="edit",
        patterns=[str(change.file_path) for change in changes],
        always=["*"],
        metadata={
            "filepath": ", ".join(str(change.file_path) for change in changes),
            "diff": total_diff,
            "files": files_metadata,
        },
    )

    for change in changes:
        if change.change_type == "add":
            change.file_path.parent.mkdir(parents=True, exist_ok=True)
            change.file_path.write_text(change.new_content, encoding="utf-8")
        elif change.change_type == "update":
            change.file_path.write_text(change.new_content, encoding="utf-8")
        elif change.change_type == "move":
            assert change.move_path is not None
            change.move_path.parent.mkdir(parents=True, exist_ok=True)
            change.move_path.write_text(change.new_content, encoding="utf-8")
            change.file_path.unlink()
        elif change.change_type == "delete":
            change.file_path.unlink()

    summary = []
    for change in changes:
        if change.change_type == "add":
            summary.append(f"A {change.file_path}")
        elif change.change_type == "delete":
            summary.append(f"D {change.file_path}")
        else:
            summary.append(f"M {change.move_path or change.file_path}")

    output = "Success. Updated the following files:\n" + "\n".join(summary)
    diagnostics = {}
    for change in changes:
        if change.change_type == "delete":
            continue
        target = str(change.move_path or change.file_path)
        output, per_file = await append_lsp_error_feedback(output, target, include_project_files=False)
        diagnostics.update(per_file)

    return ToolResult(
        title="apply_patch result",
        output=output,
        metadata={
            "diff": total_diff,
            "files": files_metadata,
            "diagnostics": diagnostics,
        },
    )


ApplyPatchTool = Tool.define(
    tool_id="apply_patch",
    description="Apply a multi-file patch in apply_patch grammar format.",
    parameters_type=ApplyPatchParams,
    execute_fn=apply_patch_execute,
    auto_truncate=False,
)
