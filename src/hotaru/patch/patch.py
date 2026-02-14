"""apply_patch text parser and chunk applier."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Union


class PatchParseError(ValueError):
    """Raised when patch text cannot be parsed."""


@dataclass
class UpdateFileChunk:
    """Single update chunk in an update hunk."""

    old_lines: List[str]
    new_lines: List[str]
    change_context: Optional[str] = None
    is_end_of_file: bool = False


@dataclass
class AddHunk:
    """Add-file patch hunk."""

    type: str
    path: str
    contents: str


@dataclass
class DeleteHunk:
    """Delete-file patch hunk."""

    type: str
    path: str


@dataclass
class UpdateHunk:
    """Update-file patch hunk."""

    type: str
    path: str
    move_path: Optional[str]
    chunks: List[UpdateFileChunk]


Hunk = Union[AddHunk, DeleteHunk, UpdateHunk]


def _strip_heredoc(text: str) -> str:
    # Supports: cat <<'EOF' ... EOF
    match = re.match(r"^(?:cat\s+)?<<['\"]?(\w+)['\"]?\s*\n([\s\S]*?)\n\1\s*$", text)
    if match:
        return match.group(2)
    return text


def parse_patch(patch_text: str) -> List[Hunk]:
    """Parse apply_patch text into structured hunks."""
    normalized = _strip_heredoc(patch_text.replace("\r\n", "\n").replace("\r", "\n").strip("\n"))
    lines = normalized.split("\n")

    try:
        begin = lines.index("*** Begin Patch")
        end = lines.index("*** End Patch")
    except ValueError as exc:
        raise PatchParseError("Invalid patch format: missing Begin/End markers") from exc

    if begin >= end:
        raise PatchParseError("Invalid patch format: malformed Begin/End markers")

    i = begin + 1
    hunks: List[Hunk] = []
    while i < end:
        line = lines[i]
        if line.startswith("*** Add File:"):
            rel_path = line.split(":", 1)[1].strip()
            i += 1
            body: List[str] = []
            while i < end and not lines[i].startswith("***"):
                chunk = lines[i]
                if not chunk.startswith("+"):
                    raise PatchParseError(f"Invalid add-file line: {chunk!r}")
                body.append(chunk[1:])
                i += 1
            content = "\n".join(body)
            hunks.append(AddHunk(type="add", path=rel_path, contents=content))
            continue

        if line.startswith("*** Delete File:"):
            rel_path = line.split(":", 1)[1].strip()
            hunks.append(DeleteHunk(type="delete", path=rel_path))
            i += 1
            continue

        if line.startswith("*** Update File:"):
            rel_path = line.split(":", 1)[1].strip()
            i += 1
            move_path: Optional[str] = None
            if i < end and lines[i].startswith("*** Move to:"):
                move_path = lines[i].split(":", 1)[1].strip()
                i += 1

            chunks: List[UpdateFileChunk] = []
            while i < end and not lines[i].startswith("***"):
                if not lines[i].startswith("@@"):
                    i += 1
                    continue
                context = lines[i][2:].strip() or None
                i += 1
                old_lines: List[str] = []
                new_lines: List[str] = []
                eof = False
                while i < end and not lines[i].startswith("@@") and not lines[i].startswith("***"):
                    entry = lines[i]
                    if entry == "*** End of File":
                        eof = True
                        i += 1
                        break
                    if entry.startswith(" "):
                        val = entry[1:]
                        old_lines.append(val)
                        new_lines.append(val)
                    elif entry.startswith("-"):
                        old_lines.append(entry[1:])
                    elif entry.startswith("+"):
                        new_lines.append(entry[1:])
                    else:
                        raise PatchParseError(f"Invalid change line: {entry!r}")
                    i += 1
                chunks.append(
                    UpdateFileChunk(
                        old_lines=old_lines,
                        new_lines=new_lines,
                        change_context=context,
                        is_end_of_file=eof,
                    )
                )
            hunks.append(UpdateHunk(type="update", path=rel_path, move_path=move_path, chunks=chunks))
            continue

        i += 1

    return hunks


def _seek_sequence(haystack: Sequence[str], needle: Sequence[str], start: int) -> int:
    if not needle:
        return start
    max_start = len(haystack) - len(needle)
    for idx in range(max(start, 0), max_start + 1):
        if list(haystack[idx : idx + len(needle)]) == list(needle):
            return idx
    return -1


def derive_new_contents_from_chunks(file_path: str, chunks: List[UpdateFileChunk], original_content: str) -> str:
    """Apply update chunks to existing file content."""
    lines = original_content.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]

    replacements: List[tuple[int, int, List[str]]] = []
    cursor = 0

    for chunk in chunks:
        if chunk.change_context:
            context_idx = _seek_sequence(lines, [chunk.change_context], cursor)
            if context_idx < 0:
                raise PatchParseError(f"Failed to find context '{chunk.change_context}' in {file_path}")
            cursor = context_idx

        idx = _seek_sequence(lines, chunk.old_lines, cursor)
        if idx < 0 and chunk.old_lines:
            idx = _seek_sequence(lines, chunk.old_lines, 0)
        if idx < 0 and chunk.old_lines:
            raise PatchParseError(f"Failed to locate target lines for patch in {file_path}")

        if idx < 0:
            idx = cursor

        replacements.append((idx, idx + len(chunk.old_lines), list(chunk.new_lines)))
        cursor = idx + len(chunk.new_lines)

    out = list(lines)
    offset = 0
    for start, end, new_lines in replacements:
        adj_start = start + offset
        adj_end = end + offset
        out[adj_start:adj_end] = new_lines
        offset += len(new_lines) - (end - start)

    out_text = "\n".join(out)
    if not out_text.endswith("\n"):
        out_text += "\n"
    return out_text


def create_unified_diff(file_path: str, old: str, new: str) -> str:
    """Build a unified diff string."""
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=file_path,
            tofile=file_path,
            lineterm="",
        )
    )

