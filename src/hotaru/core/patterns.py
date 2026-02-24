"""Shared pattern expansion utilities."""

from pathlib import Path


def expand_home(pattern: str) -> str:
    """Expand ``~/`` and ``$HOME`` prefixes to the user home directory."""
    home = str(Path.home())

    if pattern.startswith("~/"):
        return home + pattern[1:]
    if pattern == "~":
        return home
    if pattern.startswith("$HOME/"):
        return home + pattern[5:]
    if pattern.startswith("$HOME"):
        return home + pattern[5:]

    return pattern
