"""Read tool for reading file contents."""

import mimetypes
import os
from base64 import b64encode
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from ..core.id import Identifier
from ..util.log import Log
from .external_directory import assert_external_directory
from .tool import Tool, ToolContext, ToolResult

log = Log.create({"service": "read"})

DEFAULT_READ_LIMIT = 2000
MAX_LINE_LENGTH = 2000
MAX_BYTES = 50 * 1024  # 50 KB

# Binary file extensions
BINARY_EXTENSIONS = {
    ".zip", ".tar", ".gz", ".exe", ".dll", ".so", ".class", ".jar",
    ".war", ".7z", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".odt", ".ods", ".odp", ".bin", ".dat", ".obj", ".o", ".a",
    ".lib", ".wasm", ".pyc", ".pyo"
}


class ReadParams(BaseModel):
    """Parameters for the Read tool."""
    file_path: str = Field(..., description="The absolute path to the file to read")
    offset: Optional[int] = Field(None, description="The line number to start reading from (0-based)")
    limit: Optional[int] = Field(None, description="The number of lines to read (defaults to 2000)")


DESCRIPTION = """Reads a file from the local filesystem.

Usage:
- The file_path parameter must be an absolute path, not a relative path
- By default, it reads up to 2000 lines starting from the beginning of the file
- You can optionally specify a line offset and limit for long files
- Any lines longer than 2000 characters will be truncated
- Results are returned with line numbers starting at 1
- This tool can read images (PNG, JPG, etc.) and PDFs
- Binary files cannot be read and will return an error
"""


def _is_binary_file(filepath: Path) -> bool:
    """Check if a file is binary."""
    ext = filepath.suffix.lower()
    if ext in BINARY_EXTENSIONS:
        return True

    # Check file content for binary data
    try:
        with open(filepath, "rb") as f:
            chunk = f.read(4096)
            if not chunk:
                return False

            # Check for null bytes
            if b"\x00" in chunk:
                return True

            # Check for high ratio of non-printable characters
            non_printable = sum(1 for b in chunk if b < 9 or (b > 13 and b < 32))
            if len(chunk) > 0 and non_printable / len(chunk) > 0.3:
                return True

    except Exception:
        pass

    return False


async def read_execute(params: ReadParams, ctx: ToolContext) -> ToolResult:
    """Execute the read tool."""
    cwd = Path(str(ctx.extra.get("cwd") or Path.cwd()))
    filepath = Path(params.file_path)

    # Make path absolute if relative
    if not filepath.is_absolute():
        filepath = cwd / filepath

    title = filepath.name

    await assert_external_directory(ctx, filepath)

    # Request permission
    await ctx.ask(
        permission="read",
        patterns=[str(filepath)],
        always=["*"]
    )

    # Check file exists
    if not filepath.exists():
        # Try to find similar files for suggestions
        parent = filepath.parent
        base = filepath.name.lower()

        suggestions = []
        if parent.exists():
            for entry in parent.iterdir():
                if base in entry.name.lower() or entry.name.lower() in base:
                    suggestions.append(str(entry))
                    if len(suggestions) >= 3:
                        break

        if suggestions:
            raise FileNotFoundError(
                f"File not found: {filepath}\n\n"
                f"Did you mean one of these?\n" + "\n".join(suggestions)
            )
        raise FileNotFoundError(f"File not found: {filepath}")

    # Check for image or PDF
    mime_type, _ = mimetypes.guess_type(str(filepath))

    is_image = mime_type and mime_type.startswith("image/") and mime_type not in ("image/svg+xml",)
    is_pdf = mime_type == "application/pdf"

    if is_image or is_pdf:
        content = filepath.read_bytes()
        encoded = b64encode(content).decode("ascii")
        msg = f"{'Image' if is_image else 'PDF'} read successfully"

        return ToolResult(
            title=title,
            output=msg,
            metadata={
                "preview": msg,
                "truncated": False,
            },
            attachments=[{
                "id": Identifier.ascending("part"),
                "session_id": ctx.session_id,
                "message_id": ctx.message_id,
                "type": "file",
                "mime": mime_type,
                "url": f"data:{mime_type};base64,{encoded}",
            }]
        )

    # Check for binary file
    if _is_binary_file(filepath):
        raise ValueError(f"Cannot read binary file: {filepath}")

    # Read text file
    limit = params.limit or DEFAULT_READ_LIMIT
    offset = params.offset or 0

    text = filepath.read_text(encoding="utf-8", errors="replace")
    lines = text.split("\n")

    # Read lines with limits
    raw: list[str] = []
    current_bytes = 0
    truncated_by_bytes = False

    for i in range(offset, min(len(lines), offset + limit)):
        line = lines[i]
        if len(line) > MAX_LINE_LENGTH:
            line = line[:MAX_LINE_LENGTH] + "..."

        line_bytes = len(line.encode("utf-8")) + (1 if raw else 0)
        if current_bytes + line_bytes > MAX_BYTES:
            truncated_by_bytes = True
            break

        raw.append(line)
        current_bytes += line_bytes

    # Format output with line numbers
    content_lines = [
        f"{str(i + offset + 1).zfill(5)}| {line}"
        for i, line in enumerate(raw)
    ]
    preview = "\n".join(raw[:20])

    output = "<file>\n"
    output += "\n".join(content_lines)

    total_lines = len(lines)
    last_read_line = offset + len(raw)
    has_more_lines = total_lines > last_read_line
    truncated = has_more_lines or truncated_by_bytes

    if truncated_by_bytes:
        output += f"\n\n(Output truncated at {MAX_BYTES} bytes. Use 'offset' parameter to read beyond line {last_read_line})"
    elif has_more_lines:
        output += f"\n\n(File has more lines. Use 'offset' parameter to read beyond line {last_read_line})"
    else:
        output += f"\n\n(End of file - total {total_lines} lines)"

    output += "\n</file>"

    return ToolResult(
        title=title,
        output=output,
        metadata={
            "preview": preview,
            "truncated": truncated,
        }
    )


# Register the tool
ReadTool = Tool.define(
    tool_id="read",
    description=DESCRIPTION,
    parameters_type=ReadParams,
    execute_fn=read_execute,
    auto_truncate=False  # We handle truncation ourselves
)
