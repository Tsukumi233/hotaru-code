"""Bash tool for executing shell commands."""

import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

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


DESCRIPTION = f"""Executes a shell command.

Usage:
- Commands are executed in the system shell
- Default timeout is 2 minutes
- Output is truncated if it exceeds {Truncate.MAX_LINES} lines or {Truncate.MAX_BYTES} bytes
- Use 'workdir' parameter instead of 'cd' commands
- Always provide a clear description of what the command does

Examples:
- "git status" → "Shows working tree status"
- "npm install" → "Installs package dependencies"
- "mkdir foo" → "Creates directory 'foo'"
"""


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

    # Request permission
    await ctx.ask(
        permission="bash",
        patterns=[params.command],
        always=["*"],
        metadata={}
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
