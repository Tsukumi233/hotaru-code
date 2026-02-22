"""Read tool for reading file contents."""

import asyncio
import mimetypes
import os
from base64 import b64encode
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from ..core.id import Identifier
from ..util.log import Log
from .external_directory import assert_external_directory
from .tool import PermissionSpec, Tool, ToolContext, ToolResult

log = Log.create({"service": "read"})

DESCRIPTION = (Path(__file__).parent / "read.txt").read_text(encoding="utf-8")

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
    file_path: str = Field(..., alias="filePath", description="The absolute path to the file or directory to read")
    offset: Optional[int] = Field(None, description="The line number to start reading from (1-based)")
    limit: Optional[int] = Field(None, description="The number of lines to read (defaults to 2000)")

    model_config = ConfigDict(populate_by_name=True)


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


async def _warm_lsp(file_path: str) -> None:
    """Best-effort LSP warmup after a successful text read."""
    try:
        from ..lsp import LSP

        await LSP.touch_file(file_path, wait_for_diagnostics=False)
    except Exception as e:
        log.warning("failed to warm LSP on read", {"file": file_path, "error": str(e)})


def _resolve_file_path(params: ReadParams, ctx: ToolContext) -> Path:
    cwd = Path(str(ctx.extra.get("cwd") or Path.cwd()))
    file_path = Path(params.file_path)
    if not file_path.is_absolute():
        file_path = cwd / file_path
    return file_path


async def read_permissions(params: ReadParams, ctx: ToolContext) -> list[PermissionSpec]:
    file_path = _resolve_file_path(params, ctx)
    specs = await assert_external_directory(ctx, file_path)
    specs.append(
        PermissionSpec(
            permission="read",
            patterns=[str(file_path)],
            always=["*"],
        )
    )
    return specs


async def read_execute(params: ReadParams, ctx: ToolContext) -> ToolResult:
    """Execute the read tool."""
    cwd = Path(str(ctx.extra.get("cwd") or Path.cwd()))
    filepath = _resolve_file_path(params, ctx)

    worktree = Path(str(ctx.extra.get("worktree") or cwd))
    try:
        title = str(filepath.relative_to(worktree))
    except ValueError:
        title = filepath.name

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

    # Directory listing mode
    if filepath.is_dir():
        offset = params.offset or 1
        if offset < 1:
            raise ValueError("offset must be greater than or equal to 1")
        limit = params.limit or DEFAULT_READ_LIMIT

        entries = []
        for child in sorted(filepath.iterdir(), key=lambda p: p.name.lower()):
            display = child.name + ("/" if child.is_dir() else "")
            entries.append(display)

        start = offset - 1
        sliced = entries[start : start + limit]
        truncated = start + len(sliced) < len(entries)
        output = "\n".join(
            [
                f"<path>{filepath}</path>",
                "<type>directory</type>",
                "<entries>",
                *sliced,
                (
                    f"(Showing {len(sliced)} of {len(entries)} entries. Use 'offset' parameter to read beyond entry {offset + len(sliced)})"
                    if truncated
                    else f"({len(entries)} entries)"
                ),
                "</entries>",
            ]
        )
        return ToolResult(
            title=title,
            output=output,
            metadata={
                "preview": "\n".join(sliced[:20]),
                "truncated": truncated,
            },
        )

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
    offset = params.offset or 1
    if offset < 1:
        raise ValueError("offset must be greater than or equal to 1")
    start = offset - 1

    text = filepath.read_text(encoding="utf-8", errors="replace")
    lines = text.split("\n")
    if start >= len(lines):
        raise ValueError(f"Offset {offset} is out of range for this file ({len(lines)} lines)")

    # Read lines with limits
    raw: list[str] = []
    current_bytes = 0
    truncated_by_bytes = False

    for i in range(start, min(len(lines), start + limit)):
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
        f"{i + offset}: {line}"
        for i, line in enumerate(raw)
    ]
    preview = "\n".join(raw[:20])

    output = f"<path>{filepath}</path>\n<type>file</type>\n<content>\n"
    output += "\n".join(content_lines)

    total_lines = len(lines)
    last_read_line = offset + len(raw) - 1
    has_more_lines = total_lines > last_read_line
    truncated = has_more_lines or truncated_by_bytes

    if truncated_by_bytes:
        output += f"\n\n(Output truncated at {MAX_BYTES} bytes. Use 'offset' parameter to read beyond line {last_read_line})"
    elif has_more_lines:
        output += f"\n\n(File has more lines. Use 'offset' parameter to read beyond line {last_read_line})"
    else:
        output += f"\n\n(End of file - total {total_lines} lines)"

    output += "\n</content>"
    asyncio.create_task(_warm_lsp(str(filepath)))

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
    permission_fn=read_permissions,
    execute_fn=read_execute,
    auto_truncate=False  # We handle truncation ourselves
)
