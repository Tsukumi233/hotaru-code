"""Shared slash-command parsing helpers."""

from __future__ import annotations

import re

_SLASH_COMMAND_PATTERN = re.compile(
    r"^/(?P<trigger>[A-Za-z0-9._-]+)(?:\s+(?P<args>.*))?$"
)


def parse_slash_command_value(value: str) -> tuple[str, str] | None:
    """Parse slash command text and return ``(trigger, args)``."""
    stripped = value.strip()
    match = _SLASH_COMMAND_PATTERN.match(stripped)
    if not match:
        return None

    trigger = (match.group("trigger") or "").strip().lower()
    args = (match.group("args") or "").strip()
    return trigger, args
