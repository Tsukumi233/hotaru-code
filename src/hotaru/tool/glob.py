"""Glob tool for finding files by pattern."""

import os
from fnmatch import fnmatch
from pathlib import Path
from typing import List, Optional, Tuple

from pydantic import BaseModel, Field

from ..util.log import Log
from .external_directory import assert_external_directory
from .tool import Tool, ToolContext, ToolResult

log = Log.create({"service": "glob"})


class GlobParams(BaseModel):
    """Parameters for the Glob tool."""
    pattern: str = Field(..., description="The glob pattern to match files against")
    path: Optional[str] = Field(
        None,
        description=(
            "The directory to search in. If not specified, the current working directory "
            "will be used. IMPORTANT: Omit this field to use the default directory. "
            "DO NOT enter 'undefined' or 'null' - simply omit it for the default behavior."
        )
    )


DESCRIPTION = """Fast file pattern matching tool.

Usage:
- Supports glob patterns like "**/*.py" or "src/**/*.ts"
- Returns matching file paths sorted by modification time
- Use this tool when you need to find files by name patterns
- Results are limited to 100 files

Examples:
- "*.py" → Python files in current directory
- "**/*.py" → All Python files recursively
- "src/**/*.ts" → TypeScript files in src directory
"""


def _match_glob(root: Path, pattern: str, limit: int = 100) -> List[Tuple[Path, float]]:
    """Match files against a glob pattern.

    Returns list of (path, mtime) tuples.
    """
    results: List[Tuple[Path, float]] = []

    # Handle ** patterns
    if "**" in pattern:
        # Split pattern at **
        parts = pattern.split("**")
        prefix = parts[0].rstrip("/\\")
        suffix = parts[1].lstrip("/\\") if len(parts) > 1 else ""

        search_root = root / prefix if prefix else root

        if not search_root.exists():
            return results

        for dirpath, dirnames, filenames in os.walk(search_root):
            # Skip hidden directories
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]

            for filename in filenames:
                if filename.startswith("."):
                    continue

                filepath = Path(dirpath) / filename

                # Check suffix pattern
                if suffix:
                    rel_path = str(filepath.relative_to(search_root))
                    if not fnmatch(rel_path, f"*{suffix}") and not fnmatch(filename, suffix):
                        continue

                try:
                    mtime = filepath.stat().st_mtime
                    results.append((filepath, mtime))
                    if len(results) >= limit:
                        return results
                except (OSError, PermissionError):
                    continue
    else:
        # Simple pattern without **
        if "/" in pattern or "\\" in pattern:
            # Pattern includes directory
            for filepath in root.glob(pattern):
                if filepath.is_file() and not filepath.name.startswith("."):
                    try:
                        mtime = filepath.stat().st_mtime
                        results.append((filepath, mtime))
                        if len(results) >= limit:
                            return results
                    except (OSError, PermissionError):
                        continue
        else:
            # Pattern is just filename
            for filepath in root.iterdir():
                if filepath.is_file() and fnmatch(filepath.name, pattern):
                    if not filepath.name.startswith("."):
                        try:
                            mtime = filepath.stat().st_mtime
                            results.append((filepath, mtime))
                            if len(results) >= limit:
                                return results
                        except (OSError, PermissionError):
                            continue

    return results


async def glob_execute(params: GlobParams, ctx: ToolContext) -> ToolResult:
    """Execute the glob tool."""
    cwd = Path(str(ctx.extra.get("cwd") or Path.cwd()))

    # Determine search path
    search_path = Path(params.path) if params.path else cwd
    if not search_path.is_absolute():
        search_path = cwd / search_path

    await assert_external_directory(ctx, search_path, kind="directory")

    # Request permission
    await ctx.ask(
        permission="glob",
        patterns=[params.pattern],
        always=["*"],
        metadata={
            "pattern": params.pattern,
            "path": params.path,
        }
    )

    if not search_path.exists():
        raise FileNotFoundError(f"Directory not found: {search_path}")

    if not search_path.is_dir():
        raise ValueError(f"Path is not a directory: {search_path}")

    limit = 100
    files = _match_glob(search_path, params.pattern, limit + 1)

    # Check if truncated
    truncated = len(files) > limit
    if truncated:
        files = files[:limit]

    # Sort by modification time (newest first)
    files.sort(key=lambda x: x[1], reverse=True)

    # Build output
    output_lines = []
    if not files:
        output_lines.append("No files found")
    else:
        output_lines.extend(str(f[0]) for f in files)
        if truncated:
            output_lines.append("")
            output_lines.append("(Results are truncated. Consider using a more specific path or pattern.)")

    try:
        title = str(search_path.relative_to(cwd)) if search_path != cwd else "."
    except ValueError:
        title = str(search_path)

    return ToolResult(
        title=title,
        output="\n".join(output_lines),
        metadata={
            "count": len(files),
            "truncated": truncated,
        }
    )


# Register the tool
GlobTool = Tool.define(
    tool_id="glob",
    description=DESCRIPTION,
    parameters_type=GlobParams,
    execute_fn=glob_execute,
    auto_truncate=False
)
