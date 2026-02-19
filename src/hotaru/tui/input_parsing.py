"""Utilities for parsing prompt input in the TUI."""

from dataclasses import dataclass
from pathlib import Path
import re
from typing import List, Optional, Tuple

from ..command.slash import parse_slash_command_value
FILE_REFERENCE_PATTERN = re.compile(
    r"""(?<!\S)@(?:"(?P<double>[^"]+)"|'(?P<single>[^']+)'|(?P<plain>\S+))"""
)


@dataclass(frozen=True)
class SlashCommandInput:
    """Parsed slash command input."""

    trigger: str
    args: str = ""


def parse_slash_command(value: str) -> Optional[SlashCommandInput]:
    """Parse a slash command with optional args.

    Returns ``None`` when the value is not a slash command.
    """
    parsed = parse_slash_command_value(value)
    if parsed is None:
        return None

    trigger, args = parsed
    return SlashCommandInput(trigger=trigger, args=args)


def extract_file_reference_tokens(value: str) -> List[str]:
    """Extract ``@path`` tokens from the prompt text."""
    tokens: List[str] = []
    seen = set()
    for match in FILE_REFERENCE_PATTERN.finditer(value):
        token = (
            match.group("double")
            or match.group("single")
            or match.group("plain")
            or ""
        ).strip()
        token = token.rstrip(",.;:")
        if not token or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    return tokens


def enrich_content_with_file_references(
    content: str,
    cwd: str,
    *,
    max_files: int = 5,
    max_file_bytes: int = 64 * 1024,
) -> Tuple[str, List[str], List[str]]:
    """Read ``@file`` references and append them to the prompt content.

    Returns:
        ``(enriched_content, attached_paths, warnings)``
    """
    tokens = extract_file_reference_tokens(content)
    if not tokens:
        return content, [], []

    warnings: List[str] = []
    attached_paths: List[str] = []
    attachments: List[str] = []
    cwd_path = Path(cwd).resolve()

    for token in tokens[:max_files]:
        candidate = Path(token).expanduser()
        resolved = candidate if candidate.is_absolute() else (cwd_path / candidate)
        resolved = resolved.resolve()

        if not resolved.exists():
            warnings.append(f"Referenced file not found: {token}")
            continue
        if not resolved.is_file():
            warnings.append(f"Referenced path is not a file: {token}")
            continue

        file_size = resolved.stat().st_size
        if file_size > max_file_bytes:
            warnings.append(
                f"Referenced file is too large (>{max_file_bytes} bytes): {token}"
            )
            continue

        try:
            text = resolved.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            warnings.append(f"Referenced file is not UTF-8 text: {token}")
            continue
        except Exception:
            warnings.append(f"Failed to read referenced file: {token}")
            continue

        try:
            display_path = str(resolved.relative_to(cwd_path))
        except ValueError:
            display_path = str(resolved)

        attached_paths.append(display_path)
        attachments.append(
            "\n".join(
                [
                    f"<attached_file path=\"{display_path}\">",
                    text,
                    "</attached_file>",
                ]
            )
        )

    if len(tokens) > max_files:
        skipped = len(tokens) - max_files
        warnings.append(f"Only the first {max_files} file references were attached ({skipped} skipped).")

    if not attachments:
        return content, [], warnings

    enriched = content.rstrip() + "\n\n" + "\n\n".join(attachments)
    return enriched, attached_paths, warnings
