"""List tool for displaying directory trees."""

import os
from fnmatch import fnmatch
from pathlib import Path
from typing import List, Optional, Set

from pydantic import BaseModel, Field

from .external_directory import assert_external_directory
from .tool import Tool, ToolContext, ToolResult

LIMIT = 100

IGNORE_PATTERNS = [
    "node_modules/",
    "__pycache__/",
    ".git/",
    "dist/",
    "build/",
    "target/",
    "vendor/",
    "bin/",
    "obj/",
    ".idea/",
    ".vscode/",
    ".zig-cache/",
    "zig-out",
    ".coverage",
    "coverage/",
    "tmp/",
    "temp/",
    ".cache/",
    "cache/",
    "logs/",
    ".venv/",
    "venv/",
    "env/",
]


class ListParams(BaseModel):
    """Parameters for the list tool."""

    path: Optional[str] = Field(
        None,
        description="The absolute path to the directory to list (must be absolute, not relative)",
    )
    ignore: Optional[List[str]] = Field(
        None,
        description="List of glob patterns to ignore",
    )


DESCRIPTION = (Path(__file__).parent / "ls.txt").read_text(encoding="utf-8")


def _normalize(path_value: str) -> str:
    return path_value.replace("\\", "/")


def _matches_ignore(relative_path: str, is_dir: bool, patterns: List[str]) -> bool:
    rel = _normalize(relative_path)
    name = Path(relative_path).name

    for pattern in patterns:
        normalized = _normalize(pattern)

        if normalized.endswith("/"):
            base = normalized[:-1]
            if is_dir and (rel == base or rel.startswith(base + "/")):
                return True
            continue

        if fnmatch(rel, normalized) or fnmatch(name, normalized):
            return True

    return False


def _render_tree(root: Path, files: List[str]) -> str:
    dirs: Set[str] = {"."}
    files_by_dir: dict[str, List[str]] = {}

    for file in files:
        directory = str(Path(file).parent).replace("\\", "/")
        if directory == "":
            directory = "."

        parts = [] if directory == "." else directory.split("/")
        for index in range(len(parts) + 1):
            dirs.add("." if index == 0 else "/".join(parts[:index]))

        files_by_dir.setdefault(directory, []).append(Path(file).name)

    def render_dir(dir_path: str, depth: int) -> str:
        indent = "  " * depth
        output = ""

        if depth > 0:
            output += f"{indent}{Path(dir_path).name}/\n"

        child_indent = "  " * (depth + 1)
        children = sorted(
            child for child in dirs if child != dir_path and Path(child).parent.as_posix() == dir_path
        )

        for child in children:
            output += render_dir(child, depth + 1)

        for filename in sorted(files_by_dir.get(dir_path, [])):
            output += f"{child_indent}{filename}\n"

        return output

    return f"{root}/\n" + render_dir(".", 0)


async def list_execute(params: ListParams, ctx: ToolContext) -> ToolResult:
    """Execute the list tool."""

    cwd = Path(str(ctx.extra.get("cwd") or Path.cwd()))
    search_path = Path(params.path) if params.path else cwd
    if not search_path.is_absolute():
        search_path = cwd / search_path
    search_path = search_path.resolve()

    await assert_external_directory(ctx, search_path, kind="directory")

    await ctx.ask(
        permission="list",
        patterns=[str(search_path)],
        always=["*"],
        metadata={"path": str(search_path)},
    )

    if not search_path.exists():
        raise FileNotFoundError(f"Directory not found: {search_path}")
    if not search_path.is_dir():
        raise ValueError(f"Path is not a directory: {search_path}")

    ignore_patterns = IGNORE_PATTERNS + (params.ignore or [])
    collected: List[str] = []

    for dirpath, dirnames, filenames in os.walk(search_path):
        if ctx.aborted:
            break

        rel_dir = Path(dirpath).relative_to(search_path)
        rel_dir_str = "." if str(rel_dir) == "." else _normalize(str(rel_dir))

        filtered_dirs = []
        for dirname in dirnames:
            rel = dirname if rel_dir_str == "." else f"{rel_dir_str}/{dirname}"
            if not _matches_ignore(rel, True, ignore_patterns):
                filtered_dirs.append(dirname)
        dirnames[:] = filtered_dirs

        for filename in filenames:
            rel = filename if rel_dir_str == "." else f"{rel_dir_str}/{filename}"
            if _matches_ignore(rel, False, ignore_patterns):
                continue
            collected.append(rel)
            if len(collected) >= LIMIT:
                break

        if len(collected) >= LIMIT:
            break

    truncated = len(collected) >= LIMIT
    output = _render_tree(search_path, collected)

    try:
        title = str(search_path.relative_to(cwd))
    except ValueError:
        title = str(search_path)

    return ToolResult(
        title=title,
        output=output,
        metadata={
            "count": len(collected),
            "truncated": truncated,
        },
    )


LsTool = Tool.define(
    tool_id="ls",
    description=DESCRIPTION,
    parameters_type=ListParams,
    execute_fn=list_execute,
    auto_truncate=False,
)
