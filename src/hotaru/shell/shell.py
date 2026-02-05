"""Shell execution utilities.

This module provides utilities for executing shell commands and managing
shell processes. It handles platform-specific differences between Windows,
macOS, and Linux.

Key features:
- Cross-platform shell detection
- Process tree termination
- Timeout handling
- Output capture with streaming

Example:
    from hotaru.shell import Shell

    # Get the preferred shell
    shell = Shell.preferred()

    # Execute a command
    result = await Shell.run("ls -la", timeout=30.0)
    print(result.stdout)

    # Execute with streaming output
    async for line in Shell.stream("npm install"):
        print(line)
"""

import asyncio
import os
import platform
import shutil
import signal
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, Callable, Dict, List, Optional, Union

from ..util.log import Log

log = Log.create({"service": "shell"})

# Timeout for SIGKILL after SIGTERM (milliseconds)
SIGKILL_TIMEOUT_MS = 200

# Shells that are not recommended for command execution
BLACKLISTED_SHELLS = {"fish", "nu", "nushell"}

# Default command timeout (seconds)
DEFAULT_TIMEOUT = 120.0

# Maximum output size (bytes)
MAX_OUTPUT_SIZE = 1024 * 1024  # 1 MB


@dataclass
class ShellResult:
    """Result of a shell command execution.

    Attributes:
        exit_code: Process exit code (0 = success)
        stdout: Standard output content
        stderr: Standard error content
        timed_out: Whether the command timed out
        killed: Whether the process was killed
    """
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    killed: bool = False

    @property
    def success(self) -> bool:
        """Check if the command succeeded."""
        return self.exit_code == 0 and not self.timed_out and not self.killed

    @property
    def output(self) -> str:
        """Get combined stdout and stderr."""
        parts = []
        if self.stdout:
            parts.append(self.stdout)
        if self.stderr:
            parts.append(self.stderr)
        return "\n".join(parts)


class Shell:
    """Shell execution utilities.

    Provides cross-platform shell command execution with proper
    process management and output handling.
    """

    _preferred_shell: Optional[str] = None
    _acceptable_shell: Optional[str] = None

    @classmethod
    def _find_git_bash(cls) -> Optional[str]:
        """Find Git Bash on Windows.

        Returns:
            Path to bash.exe if found, None otherwise
        """
        # Check common Git installation paths
        common_paths = [
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files (x86)\Git\bin\bash.exe",
        ]

        for path in common_paths:
            if os.path.isfile(path):
                return path

        # Try to find via git.exe location
        git_path = shutil.which("git")
        if git_path:
            # git.exe is typically at: C:\Program Files\Git\cmd\git.exe
            # bash.exe is at: C:\Program Files\Git\bin\bash.exe
            git_dir = Path(git_path).parent.parent
            bash_path = git_dir / "bin" / "bash.exe"
            if bash_path.is_file():
                return str(bash_path)

        return None

    @classmethod
    def _fallback_shell(cls) -> str:
        """Get the fallback shell for the current platform.

        Returns:
            Path to a shell executable
        """
        system = platform.system()

        if system == "Windows":
            # Try Git Bash first for better Unix compatibility
            git_bash = cls._find_git_bash()
            if git_bash:
                return git_bash

            # Fall back to cmd.exe
            return os.environ.get("COMSPEC", "cmd.exe")

        elif system == "Darwin":
            # macOS default is zsh
            return "/bin/zsh"

        else:
            # Linux and others
            bash = shutil.which("bash")
            if bash:
                return bash
            return "/bin/sh"

    @classmethod
    def preferred(cls) -> str:
        """Get the user's preferred shell.

        Returns the SHELL environment variable if set,
        otherwise returns a platform-appropriate default.

        Returns:
            Path to shell executable
        """
        if cls._preferred_shell is not None:
            return cls._preferred_shell

        shell = os.environ.get("SHELL")
        if shell:
            cls._preferred_shell = shell
            return shell

        cls._preferred_shell = cls._fallback_shell()
        return cls._preferred_shell

    @classmethod
    def acceptable(cls) -> str:
        """Get an acceptable shell for command execution.

        Similar to preferred(), but excludes shells that don't work
        well for non-interactive command execution (fish, nushell).

        Returns:
            Path to shell executable
        """
        if cls._acceptable_shell is not None:
            return cls._acceptable_shell

        shell = os.environ.get("SHELL")
        if shell:
            shell_name = Path(shell).name.lower()
            if shell_name not in BLACKLISTED_SHELLS:
                cls._acceptable_shell = shell
                return shell

        cls._acceptable_shell = cls._fallback_shell()
        return cls._acceptable_shell

    @classmethod
    async def kill_tree(
        cls,
        process: asyncio.subprocess.Process,
        exited: Optional[Callable[[], bool]] = None,
    ) -> None:
        """Kill a process and all its children.

        On Unix, sends SIGTERM to the process group, waits briefly,
        then sends SIGKILL if still running.

        On Windows, uses taskkill with /T flag to kill the tree.

        Args:
            process: The process to kill
            exited: Optional callback to check if process has exited
        """
        pid = process.pid
        if pid is None:
            return

        if exited and exited():
            return

        system = platform.system()

        if system == "Windows":
            # Use taskkill to kill the process tree
            try:
                kill_proc = await asyncio.create_subprocess_exec(
                    "taskkill", "/pid", str(pid), "/f", "/t",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await kill_proc.wait()
            except Exception as e:
                log.warn("taskkill failed", {"pid": pid, "error": str(e)})
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
        else:
            # Unix: try to kill the process group
            try:
                # Send SIGTERM to process group
                os.killpg(pid, signal.SIGTERM)
                await asyncio.sleep(SIGKILL_TIMEOUT_MS / 1000)

                if not (exited and exited()):
                    # Send SIGKILL if still running
                    os.killpg(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                # Process group doesn't exist or no permission
                try:
                    process.terminate()
                    await asyncio.sleep(SIGKILL_TIMEOUT_MS / 1000)
                    if not (exited and exited()):
                        process.kill()
                except ProcessLookupError:
                    pass

    @classmethod
    async def run(
        cls,
        command: str,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        timeout: float = DEFAULT_TIMEOUT,
        shell: Optional[str] = None,
    ) -> ShellResult:
        """Execute a shell command and wait for completion.

        Args:
            command: Command to execute
            cwd: Working directory (defaults to current directory)
            env: Environment variables (merged with current environment)
            timeout: Maximum execution time in seconds
            shell: Shell to use (defaults to acceptable())

        Returns:
            ShellResult with exit code and output
        """
        shell_path = shell or cls.acceptable()
        work_dir = cwd or os.getcwd()

        # Merge environment
        full_env = os.environ.copy()
        if env:
            full_env.update(env)

        log.info("running command", {
            "command": command[:100],
            "cwd": work_dir,
            "shell": shell_path,
        })

        # Determine shell arguments
        system = platform.system()
        if system == "Windows" and shell_path.endswith("cmd.exe"):
            shell_args = [shell_path, "/c", command]
        else:
            shell_args = [shell_path, "-c", command]

        try:
            # Create process
            process = await asyncio.create_subprocess_exec(
                *shell_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=work_dir,
                env=full_env,
                start_new_session=True if system != "Windows" else False,
            )

            exited = False

            def check_exited() -> bool:
                return exited

            try:
                # Wait for completion with timeout
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout,
                )
                exited = True

                # Decode output
                stdout = stdout_bytes.decode("utf-8", errors="replace")
                stderr = stderr_bytes.decode("utf-8", errors="replace")

                # Truncate if too large
                if len(stdout) > MAX_OUTPUT_SIZE:
                    stdout = stdout[:MAX_OUTPUT_SIZE] + "\n... (output truncated)"
                if len(stderr) > MAX_OUTPUT_SIZE:
                    stderr = stderr[:MAX_OUTPUT_SIZE] + "\n... (output truncated)"

                return ShellResult(
                    exit_code=process.returncode or 0,
                    stdout=stdout,
                    stderr=stderr,
                )

            except asyncio.TimeoutError:
                log.warn("command timed out", {"command": command[:100], "timeout": timeout})
                await cls.kill_tree(process, check_exited)
                exited = True

                return ShellResult(
                    exit_code=-1,
                    stderr=f"Command timed out after {timeout} seconds",
                    timed_out=True,
                )

        except Exception as e:
            log.error("command execution failed", {"command": command[:100], "error": str(e)})
            return ShellResult(
                exit_code=-1,
                stderr=str(e),
            )

    @classmethod
    async def stream(
        cls,
        command: str,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        timeout: float = DEFAULT_TIMEOUT,
        shell: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """Execute a command and stream output line by line.

        Args:
            command: Command to execute
            cwd: Working directory
            env: Environment variables
            timeout: Maximum execution time
            shell: Shell to use

        Yields:
            Output lines as they become available
        """
        shell_path = shell or cls.acceptable()
        work_dir = cwd or os.getcwd()

        full_env = os.environ.copy()
        if env:
            full_env.update(env)

        system = platform.system()
        if system == "Windows" and shell_path.endswith("cmd.exe"):
            shell_args = [shell_path, "/c", command]
        else:
            shell_args = [shell_path, "-c", command]

        process = await asyncio.create_subprocess_exec(
            *shell_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=work_dir,
            env=full_env,
            start_new_session=True if system != "Windows" else False,
        )

        try:
            start_time = asyncio.get_event_loop().time()

            while True:
                # Check timeout
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed > timeout:
                    await cls.kill_tree(process)
                    yield f"\n[Command timed out after {timeout} seconds]"
                    break

                # Read a line with timeout
                try:
                    line = await asyncio.wait_for(
                        process.stdout.readline(),
                        timeout=min(1.0, timeout - elapsed),
                    )
                except asyncio.TimeoutError:
                    continue

                if not line:
                    break

                yield line.decode("utf-8", errors="replace").rstrip("\n\r")

        finally:
            if process.returncode is None:
                await cls.kill_tree(process)
