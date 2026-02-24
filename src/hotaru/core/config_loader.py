"""Configuration file loading utilities — JSONC parsing, env substitution, deep merge."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict

import commentjson

from ..util.log import Log

log = Log.create({"service": "config.loader"})


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Deep merge two dictionaries."""
    result = base.copy()

    for key, value in override.items():
        if (
            key in {"plugin", "instructions"}
            and isinstance(result.get(key), list)
            and isinstance(value, list)
        ):
            merged = []
            for item in [*result[key], *value]:
                if item not in merged:
                    merged.append(item)
            result[key] = merged
        elif key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value

    return result


def substitute_env_vars(text: str) -> str:
    """Replace ``{env:VAR}`` patterns with environment variable values."""
    def replacer(match: re.Match[str]) -> str:
        return os.environ.get(match.group(1), "")

    return re.sub(r'\{env:([^}]+)\}', replacer, text)


def load_json_file(filepath: str) -> Dict[str, Any]:
    """Load a JSON or JSONC file, returning ``{}`` on any I/O or parse error."""
    path = Path(filepath)
    if not path.exists():
        return {}

    try:
        text = path.read_text(encoding="utf-8")
        text = substitute_env_vars(text)
        return commentjson.loads(text)
    except (OSError, ValueError, UnicodeDecodeError) as e:
        log.error("failed to load config file", {"path": filepath, "error": str(e)})
        return {}
