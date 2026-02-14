"""Write tool for creating or overwriting files."""

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from ..util.log import Log
from .external_directory import assert_external_directory
from .lsp_feedback import append_lsp_error_feedback
from .tool import Tool, ToolContext, ToolResult

log = Log.create({"service": "write"})


class WriteParams(BaseModel):
    """Parameters for the Write tool."""
    file_path: str = Field(..., description="The absolute path to the file to write (must be absolute, not relative)")
    content: str = Field(..., description="The content to write to the file")


DESCRIPTION = """Writes content to a file, creating it if it doesn't exist or overwriting if it does.

Usage:
- The file_path parameter must be an absolute path
- Parent directories will be created if they don't exist
- The entire content will be written, replacing any existing content
- Use the Edit tool instead if you only want to modify part of a file
"""


def _create_diff(old_content: str, new_content: str, filepath: str) -> str:
    """Create a unified diff between old and new content."""
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)

    import difflib
    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=filepath,
        tofile=filepath,
        lineterm=""
    )

    return "".join(diff)


async def write_execute(params: WriteParams, ctx: ToolContext) -> ToolResult:
    """Execute the write tool."""
    cwd = Path(str(ctx.extra.get("cwd") or Path.cwd()))
    filepath = Path(params.file_path)

    # Make path absolute if relative
    if not filepath.is_absolute():
        filepath = cwd / filepath

    title = filepath.name

    await assert_external_directory(ctx, filepath)

    # Check if file exists and get old content
    exists = filepath.exists()
    content_old = ""
    if exists:
        try:
            content_old = filepath.read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass

    # Create diff for permission request
    diff = _create_diff(content_old, params.content, str(filepath))

    # Request permission
    await ctx.ask(
        permission="edit",
        patterns=[str(filepath)],
        always=["*"],
        metadata={
            "filepath": str(filepath),
            "diff": diff,
        }
    )

    # Ensure parent directory exists
    filepath.parent.mkdir(parents=True, exist_ok=True)

    # Write the file
    filepath.write_text(params.content, encoding="utf-8")

    output = "Wrote file successfully."
    output, diagnostics = await append_lsp_error_feedback(
        output=output,
        file_path=str(filepath),
        include_project_files=True,
    )

    return ToolResult(
        title=title,
        output=output,
        metadata={
            "diagnostics": diagnostics,
            "filepath": str(filepath),
            "exists": exists,
            "truncated": False,
        }
    )


# Register the tool
WriteTool = Tool.define(
    tool_id="write",
    description=DESCRIPTION,
    parameters_type=WriteParams,
    execute_fn=write_execute,
    auto_truncate=False
)
