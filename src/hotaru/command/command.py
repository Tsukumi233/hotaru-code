"""Built-in command templates.

This module ports OpenCode's built-in ``/init`` command behavior.
"""

import re
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from ..core.bus import Bus, BusEvent

_PROMPT_DIR = Path(__file__).parent / "template"
_INIT_TEMPLATE_FALLBACK = """Please analyze this codebase and create an AGENTS.md file containing:
1. Build/lint/test commands - especially for running a single test
2. Code style guidelines including imports, formatting, types, naming conventions, error handling, etc.

The file you create will be given to agentic coding agents (such as yourself) that operate in this repository. Make it about 150 lines long.
If there are Cursor rules (in .cursor/rules/ or .cursorrules) or Copilot rules (in .github/copilot-instructions.md), make sure to include them.

If there's already an AGENTS.md, improve it if it's located in ${path}

$ARGUMENTS
"""

try:
    _INIT_TEMPLATE = (_PROMPT_DIR / "initialize.txt").read_text(encoding="utf-8")
except Exception:
    _INIT_TEMPLATE = _INIT_TEMPLATE_FALLBACK

_SLASH_COMMAND_PATTERN = re.compile(
    r"^/(?P<trigger>[A-Za-z0-9._-]+)(?:\s+(?P<args>.*))?$"
)


class CommandExecutedProperties(BaseModel):
    """Payload for command execution events."""

    name: str
    project_id: str
    arguments: str = ""
    session_id: Optional[str] = None
    message_id: Optional[str] = None


class CommandEvent:
    """Command bus events."""

    Executed = BusEvent.define("command.executed", CommandExecutedProperties)


def parse_builtin_slash_command(value: str) -> Optional[tuple[str, str]]:
    """Parse built-in slash command trigger and arguments."""
    stripped = value.strip()
    match = _SLASH_COMMAND_PATTERN.match(stripped)
    if not match:
        return None

    trigger = (match.group("trigger") or "").strip().lower()
    args = (match.group("args") or "").strip()
    return trigger, args


def render_init_prompt(worktree: str, arguments: str = "") -> str:
    """Render the ``/init`` template.

    Args:
        worktree: Project boundary/worktree path.
        arguments: Extra user arguments after ``/init``.
    """
    prompt = _INIT_TEMPLATE.replace("${path}", worktree)
    prompt = prompt.replace("$ARGUMENTS", arguments.strip())
    return prompt.strip()


def expand_builtin_slash_command(value: str, worktree: str) -> Optional[str]:
    """Expand built-in slash commands into plain prompts.

    Returns ``None`` when input is not a supported built-in slash command.
    """
    parsed = parse_builtin_slash_command(value)
    if not parsed:
        return None

    trigger, args = parsed

    if trigger == "init":
        return render_init_prompt(worktree=worktree, arguments=args)
    return None


async def publish_command_executed(
    *,
    name: str,
    project_id: str,
    arguments: str = "",
    session_id: Optional[str] = None,
    message_id: Optional[str] = None,
) -> None:
    """Publish a command-executed event."""
    await Bus.publish(
        CommandEvent.Executed,
        CommandExecutedProperties(
            name=name,
            project_id=project_id,
            arguments=arguments,
            session_id=session_id,
            message_id=message_id,
        ),
    )
