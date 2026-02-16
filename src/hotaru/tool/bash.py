"""Bash tool for executing shell commands."""

import asyncio
import os
import shlex
import shutil
import sys
from pathlib import Path
from typing import Optional, Set

from pydantic import BaseModel, Field

from ..permission.arity import BashArity
from ..util.log import Log
from .external_directory import assert_external_directory
from .tool import Tool, ToolContext, ToolResult
from .truncation import Truncate

log = Log.create({"service": "bash"})

MAX_METADATA_LENGTH = 30_000
DEFAULT_TIMEOUT = 2 * 60 * 1000  # 2 minutes in ms


class BashParams(BaseModel):
    """Parameters for the Bash tool."""
    command: str = Field(..., description="The command to execute")
    timeout: Optional[int] = Field(None, description="Optional timeout in milliseconds")
    workdir: Optional[str] = Field(None, description="The working directory to run the command in")
    description: str = Field(
        ...,
        description="Clear, concise description of what this command does in 5-10 words"
    )


DESCRIPTION = (
    (Path(__file__).parent / "bash.txt")
    .read_text(encoding="utf-8")
    .replace("${maxLines}", str(Truncate.MAX_LINES))
    .replace("${maxBytes}", str(Truncate.MAX_BYTES))
)


PATH_COMMANDS = {"cd", "rm", "cp", "mv", "mkdir", "touch", "chmod", "chown", "cat"}


def _get_shell() -> str:
    """Get the appropriate shell for the current platform."""
    if sys.platform == "win32":
        # Try to find a suitable shell on Windows
        for shell in ["pwsh", "powershell", "cmd"]:
            path = shutil.which(shell)
            if path:
                return path
        return "cmd.exe"
    else:
        # Unix-like systems
        shell = os.environ.get("SHELL", "/bin/sh")
        if shutil.which(shell):
            return shell
        return "/bin/sh"


def _split_commands(command: str) -> list[str]:
    """Split shell command into top-level segments by control operators."""
    segments: list[str] = []
    current: list[str] = []
    in_single = False
    in_double = False
    escaped = False
    i = 0

    while i < len(command):
        ch = command[i]

        if escaped:
            current.append(ch)
            escaped = False
            i += 1
            continue

        if ch == "\\":
            escaped = True
            current.append(ch)
            i += 1
            continue

        if ch == "'" and not in_double:
            in_single = not in_single
            current.append(ch)
            i += 1
            continue

        if ch == '"' and not in_single:
            in_double = not in_double
            current.append(ch)
            i += 1
            continue

        if not in_single and not in_double:
            two = command[i : i + 2]
            if two in {"&&", "||"}:
                segment = "".join(current).strip()
                if segment:
                    segments.append(segment)
                current = []
                i += 2
                continue
            if ch in {"|", ";", "\n"}:
                segment = "".join(current).strip()
                if segment:
                    segments.append(segment)
                current = []
                i += 1
                continue

        current.append(ch)
        i += 1

    segment = "".join(current).strip()
    if segment:
        segments.append(segment)
    return segments


def _requires_conservative_approval(command: str) -> bool:
    """Detect shell constructs that are unsafe to parse with simple token splitting.

    For these commands we request approval for the full command string and avoid
    generating reusable always-patterns from potentially incorrect parsing.
    """
    markers = (
        "$(",
        "`",
        "<(",
        ">(",
        "<<",
        "<<<",
    )
    if any(marker in command for marker in markers):
        return True
    # Subshell/grouping can change command boundaries in ways the lightweight
    # splitter does not model.
    if "(" in command and ")" in command:
        return True
    return False


def _contains_path(base: Path, target: Path) -> bool:
    try:
        target.relative_to(base)
        return True
    except ValueError:
        return False


def _in_project_boundary(target: Path, cwd: Path, worktree: Optional[Path]) -> bool:
    if _contains_path(cwd, target):
        return True
    if worktree and str(worktree) != "/" and _contains_path(worktree, target):
        return True
    return False


def _resolve_path_argument(arg: str, cwd: Path) -> Optional[Path]:
    value = arg.strip()
    if not value:
        return None
    if value.startswith("-"):
        return None
    if any(token in value for token in ("*", "?", "[", "]", "{", "}", "$", "`", "://")):
        return None

    candidate = Path(os.path.expanduser(value))
    if not candidate.is_absolute():
        candidate = cwd / candidate

    try:
        return candidate.resolve(strict=False)
    except OSError:
        return candidate


def _parse_tokens(segment: str) -> list[str]:
    try:
        return shlex.split(segment, posix=True)
    except ValueError:
        return []


async def bash_execute(params: BashParams, ctx: ToolContext) -> ToolResult:
    """Execute the bash tool."""
    base_cwd = Path(str(ctx.extra.get("cwd") or Path.cwd()))
    cwd_path = Path(params.workdir) if params.workdir else base_cwd
    if not cwd_path.is_absolute():
        cwd_path = base_cwd / cwd_path
    cwd = str(cwd_path.resolve())

    if params.timeout is not None and params.timeout < 0:
        raise ValueError(f"Invalid timeout value: {params.timeout}. Timeout must be a positive number.")

    timeout_ms = params.timeout or DEFAULT_TIMEOUT
    timeout_sec = timeout_ms / 1000

    await assert_external_directory(ctx, cwd_path, kind="directory")

    command_patterns: list[str] = []
    always_patterns: list[str] = []
    external_globs: Set[str] = set()

    worktree_value = str(ctx.extra.get("worktree") or "")
    worktree_path = Path(worktree_value).resolve() if worktree_value else None

    if _requires_conservative_approval(params.command):
        stripped = params.command.strip()
        if stripped:
            command_patterns.append(stripped)
    else:
        segments = _split_commands(params.command)
        if not segments:
            segments = [params.command.strip()]

        for segment in segments:
            tokens = _parse_tokens(segment)
            if not tokens:
                command_patterns.append(segment)
                continue

            command_name = tokens[0]

            if command_name in PATH_COMMANDS:
                for arg in tokens[1:]:
                    if command_name == "chmod" and arg.startswith("+"):
                        continue
                    resolved = _resolve_path_argument(arg, cwd_path)
                    if not resolved:
                        continue
                    if _in_project_boundary(resolved, base_cwd.resolve(), worktree_path):
                        continue
                    parent_dir = resolved if resolved.is_dir() else resolved.parent
                    external_globs.add(str(parent_dir / "*"))

            if command_name == "cd":
                continue

            command_patterns.append(segment)
            prefix = BashArity.prefix(tokens)
            if prefix:
                always_patterns.append(" ".join(prefix) + " *")

    if external_globs:
        globs = sorted(external_globs)
        await ctx.ask(
            permission="external_directory",
            patterns=globs,
            always=globs,
            metadata={"command": params.command},
        )

    if command_patterns:
        unique_patterns = sorted(set(command_patterns))
        unique_always = sorted(set(always_patterns))
        await ctx.ask(
            permission="bash",
            patterns=unique_patterns,
            always=unique_always,
            metadata={
                "command": params.command,
                "description": params.description,
            },
        )

    shell = _get_shell()
    log.info("executing command", {"shell": shell, "command": params.command})

    # Update metadata with initial state
    ctx.metadata(metadata={
        "output": "",
        "description": params.description,
    })

    # Run the command
    try:
        if sys.platform == "win32":
            # Windows: use shell=True
            proc = await asyncio.create_subprocess_shell(
                params.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
        else:
            # Unix: pass to shell explicitly
            proc = await asyncio.create_subprocess_exec(
                shell, "-c", params.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )

        timed_out = False
        aborted = False

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout_sec
            )
        except asyncio.TimeoutError:
            timed_out = True
            proc.kill()
            stdout, stderr = await proc.communicate()

        if ctx.aborted:
            aborted = True
            try:
                proc.kill()
            except Exception:
                pass

        # Combine output
        output = ""
        if stdout:
            output += stdout.decode("utf-8", errors="replace")
        if stderr:
            if output:
                output += "\n"
            output += stderr.decode("utf-8", errors="replace")

        # Add metadata about termination
        result_metadata = []
        if timed_out:
            result_metadata.append(f"bash tool terminated command after exceeding timeout {timeout_ms} ms")
        if aborted:
            result_metadata.append("User aborted the command")

        if result_metadata:
            output += "\n\n<bash_metadata>\n" + "\n".join(result_metadata) + "\n</bash_metadata>"

        # Truncate metadata for display
        display_output = output
        if len(display_output) > MAX_METADATA_LENGTH:
            display_output = display_output[:MAX_METADATA_LENGTH] + "\n\n..."

        return ToolResult(
            title=params.description,
            output=output,
            metadata={
                "output": display_output,
                "exit": proc.returncode,
                "description": params.description,
            }
        )

    except Exception as e:
        log.error("command execution failed", {"error": str(e)})
        raise RuntimeError(f"Command execution failed: {e}") from e


# Register the tool
BashTool = Tool.define(
    tool_id="bash",
    description=DESCRIPTION,
    parameters_type=BashParams,
    execute_fn=bash_execute,
    auto_truncate=True
)
