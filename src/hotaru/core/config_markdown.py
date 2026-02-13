"""Markdown config parsing helpers.

Parses markdown files with YAML frontmatter used by command/agent configs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import yaml


_FRONTMATTER_RE = re.compile(r"^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)")


@dataclass
class MarkdownConfig:
    """Parsed markdown config payload."""

    data: Dict[str, Any]
    content: str


def _fallback_sanitization(content: str) -> str:
    """Best-effort cleanup for loosely formatted frontmatter."""
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return content

    frontmatter = match.group(1)
    lines = frontmatter.splitlines()
    result: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            result.append(line)
            continue
        if line.startswith((" ", "\t")):
            result.append(line)
            continue

        kv_match = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*(.*)$", line)
        if not kv_match:
            result.append(line)
            continue

        key, value = kv_match.group(1), kv_match.group(2).strip()
        if not value or value in {"|", ">"} or value.startswith(("'", '"')):
            result.append(line)
            continue

        if ":" in value:
            result.append(f"{key}: |-")
            result.append(f"  {value}")
            continue

        result.append(line)

    sanitized = "\n".join(result)
    return content.replace(frontmatter, sanitized, 1)


def parse_markdown_config(file_path: str) -> MarkdownConfig:
    """Parse markdown config with optional YAML frontmatter."""
    raw = Path(file_path).read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(raw)

    if not match:
        return MarkdownConfig(data={}, content=raw.strip())

    frontmatter = match.group(1)
    body = raw[match.end() :].strip()

    try:
        parsed = yaml.safe_load(frontmatter) or {}
    except Exception:
        sanitized = _fallback_sanitization(raw)
        retry = _FRONTMATTER_RE.match(sanitized)
        if not retry:
            raise
        parsed = yaml.safe_load(retry.group(1)) or {}
        body = sanitized[retry.end() :].strip()

    if not isinstance(parsed, dict):
        raise ValueError(f"Frontmatter in {file_path} must be a mapping")

    return MarkdownConfig(data=parsed, content=body)
