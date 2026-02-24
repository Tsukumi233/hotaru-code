"""Grep tool for searching file contents."""

import asyncio
import os
import re
import shutil
from pathlib import Path
from typing import List, Optional, Tuple

from pydantic import BaseModel, Field

from ..util.log import Log
from .external_directory import assert_external_directory
from .tool import PermissionSpec, Tool, ToolContext, ToolResult

log = Log.create({"service": "grep"})

DESCRIPTION = (Path(__file__).parent / "grep.txt").read_text(encoding="utf-8")

MAX_LINE_LENGTH = 2000


class GrepParams(BaseModel):
    """Parameters for the Grep tool."""
    pattern: str = Field(..., description="The regex pattern to search for in file contents")
    path: Optional[str] = Field(None, description="The directory to search in. Defaults to the current working directory.")
    include: Optional[str] = Field(None, description='File pattern to include in the search (e.g. "*.py", "*.{ts,tsx}")')


def _search_file(
    filepath: Path,
    pattern: re.Pattern,
    max_matches: int = 100
) -> List[Tuple[int, str]]:
    """Search a file for pattern matches.

    Returns list of (line_number, line_text) tuples.
    """
    matches = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            for line_num, line in enumerate(f, 1):
                if pattern.search(line):
                    # Truncate long lines
                    if len(line) > MAX_LINE_LENGTH:
                        line = line[:MAX_LINE_LENGTH] + "..."
                    matches.append((line_num, line.rstrip()))
                    if len(matches) >= max_matches:
                        break
    except (OSError, PermissionError, UnicodeDecodeError):
        pass
    return matches


def _should_include(filepath: Path, include_pattern: Optional[str]) -> bool:
    """Check if a file matches the include pattern."""
    if not include_pattern:
        return True

    from fnmatch import fnmatch

    # Handle {a,b} patterns
    if "{" in include_pattern and "}" in include_pattern:
        # Extract alternatives
        match = re.match(r'(.*)\{([^}]+)\}(.*)', include_pattern)
        if match:
            prefix, alternatives, suffix = match.groups()
            for alt in alternatives.split(","):
                pattern = f"{prefix}{alt}{suffix}"
                if fnmatch(filepath.name, pattern):
                    return True
            return False

    return fnmatch(filepath.name, include_pattern)


async def grep_execute(params: GrepParams, ctx: ToolContext) -> ToolResult:
    """Execute the grep tool."""
    if not params.pattern:
        raise ValueError("pattern is required")

    cwd = Path(ctx.cwd or str(Path.cwd()))

    search_path = _resolve_search_path(params, ctx)

    if not search_path.exists():
        raise FileNotFoundError(f"Path not found: {search_path}")

    # Compile regex
    try:
        pattern = re.compile(params.pattern)
    except re.error as e:
        raise ValueError(f"Invalid regex pattern: {e}") from e

    # Search for matches
    all_matches: List[Tuple[Path, float, int, str]] = []
    limit = 100

    if search_path.is_file():
        # Search single file
        if _should_include(search_path, params.include):
            mtime = search_path.stat().st_mtime
            for line_num, line_text in _search_file(search_path, pattern):
                all_matches.append((search_path, mtime, line_num, line_text))
                if len(all_matches) >= limit:
                    break
    else:
        # Search directory recursively
        for dirpath, dirnames, filenames in os.walk(search_path):
            # Skip hidden directories
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]

            for filename in filenames:
                if filename.startswith("."):
                    continue

                filepath = Path(dirpath) / filename

                if not _should_include(filepath, params.include):
                    continue

                try:
                    mtime = filepath.stat().st_mtime
                    for line_num, line_text in _search_file(filepath, pattern, limit - len(all_matches)):
                        all_matches.append((filepath, mtime, line_num, line_text))
                        if len(all_matches) >= limit:
                            break
                except (OSError, PermissionError):
                    continue

                if len(all_matches) >= limit:
                    break

            if len(all_matches) >= limit:
                break

    # Check truncation
    truncated = len(all_matches) >= limit

    if not all_matches:
        return ToolResult(
            title=params.pattern,
            output="No files found",
            metadata={"matches": 0, "truncated": False}
        )

    # Sort by modification time (newest first)
    all_matches.sort(key=lambda x: x[1], reverse=True)

    # Build output
    output_lines = [f"Found {len(all_matches)} matches"]

    current_file = ""
    for filepath, mtime, line_num, line_text in all_matches:
        file_str = str(filepath)
        if current_file != file_str:
            if current_file:
                output_lines.append("")
            current_file = file_str
            output_lines.append(f"{file_str}:")
        output_lines.append(f"  Line {line_num}: {line_text}")

    if truncated:
        output_lines.append("")
        output_lines.append("(Results are truncated. Consider using a more specific path or pattern.)")

    return ToolResult(
        title=params.pattern,
        output="\n".join(output_lines),
        metadata={
            "matches": len(all_matches),
            "truncated": truncated,
        }
    )


def _resolve_search_path(params: GrepParams, ctx: ToolContext) -> Path:
    from .paths import resolve_or_cwd
    return resolve_or_cwd(params.path, ctx)


async def grep_permissions(params: GrepParams, ctx: ToolContext) -> list[PermissionSpec]:
    search_path = _resolve_search_path(params, ctx)
    if not search_path.exists():
        raise FileNotFoundError(f"Path not found: {search_path}")
    specs = await assert_external_directory(
        ctx,
        search_path,
        kind="directory" if search_path.is_dir() else "file",
    )
    specs.append(
        PermissionSpec(
            permission="grep",
            patterns=[params.pattern],
            always=["*"],
            metadata={
                "pattern": params.pattern,
                "path": params.path,
                "include": params.include,
            },
        )
    )
    return specs


# Register the tool
GrepTool = Tool.define(
    tool_id="grep",
    description=DESCRIPTION,
    parameters_type=GrepParams,
    permission_fn=grep_permissions,
    execute_fn=grep_execute,
    auto_truncate=False
)
