"""Output truncation utilities.

Handles truncation of large tool outputs to fit within context limits.
"""

import asyncio
import os
from pathlib import Path
from typing import Dict, Literal, Optional, TypedDict, Union

from ..core.global_paths import GlobalPath
from ..core.id import Identifier
from ..util.log import Log

log = Log.create({"service": "truncation"})

MAX_LINES = 2000
MAX_BYTES = 50 * 1024  # 50 KB

# Retention period for saved outputs
RETENTION_MS = 7 * 24 * 60 * 60 * 1000  # 7 days
HOUR_MS = 60 * 60 * 1000


class TruncateResultNotTruncated(TypedDict):
    content: str
    truncated: Literal[False]


class TruncateResultTruncated(TypedDict):
    content: str
    truncated: Literal[True]
    output_path: str


TruncateResult = Union[TruncateResultNotTruncated, TruncateResultTruncated]


class TruncateOptions(TypedDict, total=False):
    max_lines: int
    max_bytes: int
    direction: Literal["head", "tail"]


def _get_output_dir() -> Path:
    """Get the directory for storing truncated outputs."""
    output_dir = Path(GlobalPath.data()) / "tool-output"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


class Truncate:
    """Output truncation utilities."""

    MAX_LINES = MAX_LINES
    MAX_BYTES = MAX_BYTES

    @classmethod
    async def cleanup(cls) -> None:
        """Clean up old truncated output files."""
        import time

        output_dir = _get_output_dir()
        cutoff_time = time.time() * 1000 - RETENTION_MS

        try:
            for entry in output_dir.iterdir():
                if not entry.is_file():
                    continue
                if not entry.name.startswith("tool_"):
                    continue

                # Extract timestamp from ID
                try:
                    timestamp = Identifier.timestamp(entry.name)
                    if timestamp < cutoff_time:
                        entry.unlink()
                        log.info("cleaned up old output", {"file": str(entry)})
                except Exception:
                    pass
        except Exception as e:
            log.error("cleanup failed", {"error": str(e)})

    @classmethod
    async def output(
        cls,
        text: str,
        options: Optional[TruncateOptions] = None,
        has_task_tool: bool = False
    ) -> TruncateResult:
        """Truncate output if it exceeds limits.

        Args:
            text: The text to potentially truncate
            options: Truncation options
            has_task_tool: Whether the agent has access to Task tool

        Returns:
            TruncateResult with content and truncation info
        """
        if options is None:
            options = {}

        max_lines = options.get("max_lines", MAX_LINES)
        max_bytes = options.get("max_bytes", MAX_BYTES)
        direction = options.get("direction", "head")

        lines = text.split("\n")
        total_bytes = len(text.encode("utf-8"))

        # Check if truncation is needed
        if len(lines) <= max_lines and total_bytes <= max_bytes:
            return {"content": text, "truncated": False}

        # Perform truncation
        out: list[str] = []
        current_bytes = 0
        hit_bytes = False

        if direction == "head":
            for i, line in enumerate(lines):
                if i >= max_lines:
                    break
                line_bytes = len(line.encode("utf-8")) + (1 if i > 0 else 0)
                if current_bytes + line_bytes > max_bytes:
                    hit_bytes = True
                    break
                out.append(line)
                current_bytes += line_bytes
        else:  # tail
            for i in range(len(lines) - 1, -1, -1):
                if len(out) >= max_lines:
                    break
                line = lines[i]
                line_bytes = len(line.encode("utf-8")) + (1 if out else 0)
                if current_bytes + line_bytes > max_bytes:
                    hit_bytes = True
                    break
                out.insert(0, line)
                current_bytes += line_bytes

        # Calculate removed amount
        if hit_bytes:
            removed = total_bytes - current_bytes
            unit = "bytes"
        else:
            removed = len(lines) - len(out)
            unit = "lines"

        preview = "\n".join(out)

        # Save full output to file
        output_id = Identifier.ascending("tool")
        output_dir = _get_output_dir()
        output_path = output_dir / output_id

        try:
            output_path.write_text(text, encoding="utf-8")
        except Exception as e:
            log.error("failed to save truncated output", {"error": str(e)})

        # Build hint message
        if has_task_tool:
            hint = (
                f"The tool call succeeded but the output was truncated. "
                f"Full output saved to: {output_path}\n"
                f"Use the Task tool to have explore agent process this file with "
                f"Grep and Read (with offset/limit). Do NOT read the full file yourself - "
                f"delegate to save context."
            )
        else:
            hint = (
                f"The tool call succeeded but the output was truncated. "
                f"Full output saved to: {output_path}\n"
                f"Use Grep to search the full content or Read with offset/limit "
                f"to view specific sections."
            )

        if direction == "head":
            message = f"{preview}\n\n...{removed} {unit} truncated...\n\n{hint}"
        else:
            message = f"...{removed} {unit} truncated...\n\n{hint}\n\n{preview}"

        return {
            "content": message,
            "truncated": True,
            "output_path": str(output_path)
        }


# Background cleanup task
_cleanup_task: Optional[asyncio.Task] = None


async def _periodic_cleanup():
    """Periodically clean up old output files."""
    while True:
        await asyncio.sleep(HOUR_MS / 1000)
        try:
            await Truncate.cleanup()
        except Exception:
            pass


def start_cleanup_task():
    """Start the background cleanup task."""
    global _cleanup_task
    if _cleanup_task is None:
        _cleanup_task = asyncio.create_task(_periodic_cleanup())


def stop_cleanup_task():
    """Stop the background cleanup task."""
    global _cleanup_task
    if _cleanup_task is not None:
        _cleanup_task.cancel()
        _cleanup_task = None
