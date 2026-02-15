"""Edit tool for modifying file contents with string replacement."""

import difflib
import re
from pathlib import Path
from typing import Generator, Optional

from pydantic import BaseModel, ConfigDict, Field

from ..util.log import Log
from .external_directory import assert_external_directory
from .lsp_feedback import append_lsp_error_feedback
from .tool import Tool, ToolContext, ToolResult

log = Log.create({"service": "edit"})


class EditParams(BaseModel):
    """Parameters for the Edit tool."""
    file_path: str = Field(..., alias="filePath", description="The absolute path to the file to modify")
    old_string: str = Field(..., alias="oldString", description="The text to replace")
    new_string: str = Field(
        ...,
        alias="newString",
        description="The text to replace it with (must be different from old_string)",
    )
    replace_all: Optional[bool] = Field(
        False,
        alias="replaceAll",
        description="Replace all occurrences of old_string (default false)",
    )

    model_config = ConfigDict(populate_by_name=True)


DESCRIPTION = """Performs exact string replacements in files.

Usage:
- You must read a file before editing it
- The old_string must be unique in the file (or use replace_all=true)
- old_string and new_string must be different
- Preserves exact indentation and whitespace
- Use for surgical edits rather than rewriting entire files
"""


# Similarity thresholds for fuzzy matching
SINGLE_CANDIDATE_THRESHOLD = 0.0
MULTIPLE_CANDIDATES_THRESHOLD = 0.3


def _levenshtein(a: str, b: str) -> int:
    """Calculate Levenshtein distance between two strings."""
    if not a or not b:
        return max(len(a), len(b))

    matrix = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]

    for i in range(len(a) + 1):
        matrix[i][0] = i
    for j in range(len(b) + 1):
        matrix[0][j] = j

    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            matrix[i][j] = min(
                matrix[i - 1][j] + 1,
                matrix[i][j - 1] + 1,
                matrix[i - 1][j - 1] + cost
            )

    return matrix[len(a)][len(b)]


# Replacer type
Replacer = Generator[str, None, None]


def simple_replacer(content: str, find: str) -> Replacer:
    """Direct string match."""
    yield find


def line_trimmed_replacer(content: str, find: str) -> Replacer:
    """Match with trimmed line comparison."""
    original_lines = content.split("\n")
    search_lines = find.split("\n")

    if search_lines and search_lines[-1] == "":
        search_lines.pop()

    for i in range(len(original_lines) - len(search_lines) + 1):
        matches = True
        for j in range(len(search_lines)):
            if original_lines[i + j].strip() != search_lines[j].strip():
                matches = False
                break

        if matches:
            match_start = sum(len(original_lines[k]) + 1 for k in range(i))
            match_end = match_start
            for k in range(len(search_lines)):
                match_end += len(original_lines[i + k])
                if k < len(search_lines) - 1:
                    match_end += 1
            yield content[match_start:match_end]


def block_anchor_replacer(content: str, find: str) -> Replacer:
    """Match using first/last line anchors with fuzzy middle."""
    original_lines = content.split("\n")
    search_lines = find.split("\n")

    if len(search_lines) < 3:
        return

    if search_lines and search_lines[-1] == "":
        search_lines.pop()

    first_line = search_lines[0].strip()
    last_line = search_lines[-1].strip()

    candidates = []
    for i in range(len(original_lines)):
        if original_lines[i].strip() != first_line:
            continue
        for j in range(i + 2, len(original_lines)):
            if original_lines[j].strip() == last_line:
                candidates.append((i, j))
                break

    if not candidates:
        return

    if len(candidates) == 1:
        start, end = candidates[0]
        match_start = sum(len(original_lines[k]) + 1 for k in range(start))
        match_end = match_start
        for k in range(start, end + 1):
            match_end += len(original_lines[k])
            if k < end:
                match_end += 1
        yield content[match_start:match_end]
        return

    # Multiple candidates - find best match
    best_match = None
    max_similarity = -1

    for start, end in candidates:
        actual_size = end - start + 1
        search_size = len(search_lines)
        lines_to_check = min(search_size - 2, actual_size - 2)

        if lines_to_check > 0:
            similarity = 0
            for j in range(1, min(search_size - 1, actual_size - 1)):
                orig = original_lines[start + j].strip()
                search = search_lines[j].strip()
                max_len = max(len(orig), len(search))
                if max_len > 0:
                    dist = _levenshtein(orig, search)
                    similarity += 1 - dist / max_len
            similarity /= lines_to_check
        else:
            similarity = 1.0

        if similarity > max_similarity:
            max_similarity = similarity
            best_match = (start, end)

    if max_similarity >= MULTIPLE_CANDIDATES_THRESHOLD and best_match:
        start, end = best_match
        match_start = sum(len(original_lines[k]) + 1 for k in range(start))
        match_end = match_start
        for k in range(start, end + 1):
            match_end += len(original_lines[k])
            if k < end:
                match_end += 1
        yield content[match_start:match_end]


def whitespace_normalized_replacer(content: str, find: str) -> Replacer:
    """Match with normalized whitespace."""
    def normalize(text: str) -> str:
        return re.sub(r'\s+', ' ', text).strip()

    normalized_find = normalize(find)
    lines = content.split("\n")

    for line in lines:
        if normalize(line) == normalized_find:
            yield line

    # Multi-line matches
    find_lines = find.split("\n")
    if len(find_lines) > 1:
        for i in range(len(lines) - len(find_lines) + 1):
            block = lines[i:i + len(find_lines)]
            if normalize("\n".join(block)) == normalized_find:
                yield "\n".join(block)


def trimmed_boundary_replacer(content: str, find: str) -> Replacer:
    """Match with trimmed boundaries."""
    trimmed = find.strip()
    if trimmed == find:
        return

    if trimmed in content:
        yield trimmed


REPLACERS = [
    simple_replacer,
    line_trimmed_replacer,
    block_anchor_replacer,
    whitespace_normalized_replacer,
    trimmed_boundary_replacer,
]


def replace(content: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    """Replace old_string with new_string in content.

    Tries multiple matching strategies in order of specificity.
    """
    if old_string == new_string:
        raise ValueError("old_string and new_string must be different")

    not_found = True

    for replacer_fn in REPLACERS:
        for search in replacer_fn(content, old_string):
            index = content.find(search)
            if index == -1:
                continue

            not_found = False

            if replace_all:
                return content.replace(search, new_string)

            last_index = content.rfind(search)
            if index != last_index:
                continue

            return content[:index] + new_string + content[index + len(search):]

    if not_found:
        raise ValueError("old_string not found in content")

    raise ValueError(
        "Found multiple matches for old_string. "
        "Provide more surrounding lines in old_string to identify the correct match."
    )


def trim_diff(diff: str) -> str:
    """Remove common leading whitespace from diff content lines."""
    lines = diff.split("\n")
    content_lines = [
        line for line in lines
        if (line.startswith("+") or line.startswith("-") or line.startswith(" "))
        and not line.startswith("---")
        and not line.startswith("+++")
    ]

    if not content_lines:
        return diff

    min_indent = float('inf')
    for line in content_lines:
        content = line[1:]
        if content.strip():
            match = re.match(r'^(\s*)', content)
            if match:
                min_indent = min(min_indent, len(match.group(1)))

    if min_indent == float('inf') or min_indent == 0:
        return diff

    trimmed = []
    for line in lines:
        if ((line.startswith("+") or line.startswith("-") or line.startswith(" "))
                and not line.startswith("---") and not line.startswith("+++")):
            prefix = line[0]
            content = line[1:]
            trimmed.append(prefix + content[int(min_indent):])
        else:
            trimmed.append(line)

    return "\n".join(trimmed)


async def edit_execute(params: EditParams, ctx: ToolContext) -> ToolResult:
    """Execute the edit tool."""
    if not params.file_path:
        raise ValueError("file_path is required")

    if params.old_string == params.new_string:
        raise ValueError("old_string and new_string must be different")

    filepath = Path(params.file_path)
    cwd = Path(str(ctx.extra.get("cwd") or Path.cwd()))
    if not filepath.is_absolute():
        filepath = cwd / filepath

    await assert_external_directory(ctx, filepath)

    diff = ""

    # Handle creating new file with empty old_string
    if params.old_string == "":
        existed = filepath.exists()
        content_new = params.new_string

        diff = _create_diff("", content_new, str(filepath))

        await ctx.ask(
            permission="edit",
            patterns=[str(filepath)],
            always=["*"],
            metadata={"filepath": str(filepath), "diff": diff}
        )

        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(params.new_string, encoding="utf-8")
    else:
        # Read existing file
        if not filepath.exists():
            raise FileNotFoundError(f"File {filepath} not found")

        if filepath.is_dir():
            raise ValueError(f"Path is a directory, not a file: {filepath}")

        content_old = filepath.read_text(encoding="utf-8", errors="replace")
        content_new = replace(
            content_old,
            params.old_string,
            params.new_string,
            params.replace_all or False
        )

        diff = _create_diff(content_old, content_new, str(filepath))

        await ctx.ask(
            permission="edit",
            patterns=[str(filepath)],
            always=["*"],
            metadata={"filepath": str(filepath), "diff": diff}
        )

        filepath.write_text(content_new, encoding="utf-8")

    output = "Edit applied successfully."
    output, diagnostics = await append_lsp_error_feedback(
        output=output,
        file_path=str(filepath),
    )

    return ToolResult(
        title=filepath.name,
        output=output,
        metadata={
            "diagnostics": diagnostics,
            "diff": diff,
            "truncated": False,
        }
    )


def _create_diff(old: str, new: str, filepath: str) -> str:
    """Create a unified diff."""
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)

    diff = difflib.unified_diff(
        old_lines, new_lines,
        fromfile=filepath, tofile=filepath,
        lineterm=""
    )
    return trim_diff("".join(diff))


# Register the tool
EditTool = Tool.define(
    tool_id="edit",
    description=DESCRIPTION,
    parameters_type=EditParams,
    execute_fn=edit_execute,
    auto_truncate=False
)
