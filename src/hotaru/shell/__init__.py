"""Shell execution utilities.

This module provides cross-platform shell command execution with proper
process management, timeout handling, and output streaming.

Example:
    from hotaru.shell import Shell, ShellResult

    # Execute a command
    result = await Shell.run("ls -la")
    if result.success:
        print(result.stdout)

    # Stream output
    async for line in Shell.stream("npm install"):
        print(line)

    # Get preferred shell
    shell = Shell.preferred()
"""

from .shell import Shell, ShellResult

__all__ = [
    "Shell",
    "ShellResult",
]
