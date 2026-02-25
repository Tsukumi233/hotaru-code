"""Instruction/rules loading for system prompts.

Loads rule files from project/global locations and optional instruction files
configured in ``hotaru.json`` (including remote URLs).
"""

import asyncio
import glob
import os
from pathlib import Path
from typing import List, Optional

import httpx

from ..core.config import ConfigManager
from ..core.global_paths import GlobalPath
from ..util.log import Log

log = Log.create({"service": "session.instruction"})

# Rule file precedence for local traversal: first matching type wins.
_RULE_FILES = ["AGENTS.md", "CLAUDE.md"]


def _truthy(name: str) -> bool:
    value = os.environ.get(name, "").lower()
    return value in ("1", "true")


def _disable_claude_code() -> bool:
    return _truthy("HOTARU_DISABLE_CLAUDE_CODE")


def _disable_claude_prompt() -> bool:
    return _disable_claude_code() or _truthy("HOTARU_DISABLE_CLAUDE_CODE_PROMPT")


def _disable_project_config() -> bool:
    return _truthy("HOTARU_DISABLE_PROJECT_CONFIG")


def _append_unique(items: List[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _find_up(target: str, start: str, stop: Optional[str] = None) -> List[str]:
    current = Path(start).resolve()
    stop_path = Path(stop).resolve() if stop else None
    result: List[str] = []

    while True:
        candidate = current / target
        if candidate.is_file():
            result.append(str(candidate.resolve()))
        if stop_path and current == stop_path:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent

    return result


def _glob_at(pattern: str, cwd: Path) -> List[str]:
    matches: List[str] = []
    try:
        for match in glob.glob(pattern, root_dir=str(cwd), recursive=True):
            resolved = (cwd / match).resolve()
            if resolved.is_file():
                _append_unique(matches, str(resolved))
    except Exception:
        # Invalid glob patterns are ignored for compatibility.
        pass
    return matches


def _glob_up(pattern: str, start: str, stop: Optional[str] = None) -> List[str]:
    current = Path(start).resolve()
    stop_path = Path(stop).resolve() if stop else None
    result: List[str] = []

    while True:
        for match in _glob_at(pattern, current):
            _append_unique(result, match)
        if stop_path and current == stop_path:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent

    return result


def _has_glob_chars(value: str) -> bool:
    return any(ch in value for ch in ("*", "?", "["))


def _resolve_relative_instruction(instruction: str, directory: str, worktree: Optional[str]) -> List[str]:
    if not _disable_project_config():
        return _glob_up(instruction, directory, worktree)

    config_dir = os.environ.get("HOTARU_CONFIG_DIR")
    if not config_dir:
        log.warn(
            "skipping relative instruction because HOTARU_CONFIG_DIR is not set while project config is disabled",
            {"instruction": instruction},
        )
        return []

    return _glob_up(instruction, config_dir, config_dir)


class InstructionPrompt:
    """Rule/instruction resolver used by session system prompts."""

    @classmethod
    async def system_paths(
        cls,
        directory: Optional[str] = None,
        worktree: Optional[str] = None,
    ) -> List[str]:
        """Resolve local and global instruction file paths."""
        cwd = str(Path(directory or os.getcwd()).resolve())
        config = await ConfigManager.load(cwd)
        paths: List[str] = []

        # 1) Local rule files traversing upward from cwd.
        if not _disable_project_config():
            for filename in _RULE_FILES:
                if filename == "CLAUDE.md" and _disable_claude_code():
                    continue
                matches = _find_up(filename, cwd, worktree)
                if matches:
                    for match in matches:
                        _append_unique(paths, match)
                    break

        # 2) Global fallback rules.
        global_candidates: List[Path] = []
        profile_dir = os.environ.get("HOTARU_CONFIG_DIR")
        if profile_dir:
            global_candidates.append(Path(profile_dir) / "AGENTS.md")
        global_candidates.append(Path(GlobalPath.config()) / "AGENTS.md")
        if not _disable_claude_prompt():
            global_candidates.append(Path(GlobalPath.home()) / ".claude" / "CLAUDE.md")

        for candidate in global_candidates:
            if candidate.is_file():
                _append_unique(paths, str(candidate.resolve()))
                break

        # 3) Additional instruction files from config.instructions.
        for instruction in config.instructions or []:
            if instruction.startswith(("http://", "https://")):
                continue

            expanded = instruction
            if expanded.startswith("~/"):
                expanded = str(Path(GlobalPath.home()) / expanded[2:])

            resolved: List[str] = []
            absolute = Path(expanded)
            if absolute.is_absolute():
                if absolute.is_file():
                    resolved = [str(absolute.resolve())]
                elif _has_glob_chars(expanded):
                    for match in glob.glob(expanded, recursive=True):
                        path = Path(match)
                        if path.is_file():
                            _append_unique(resolved, str(path.resolve()))
            else:
                resolved = _resolve_relative_instruction(expanded, cwd, worktree)

            for match in resolved:
                _append_unique(paths, match)

        return paths

    @classmethod
    async def system(
        cls,
        directory: Optional[str] = None,
        worktree: Optional[str] = None,
    ) -> List[str]:
        """Load system instruction text blocks."""
        cwd = str(Path(directory or os.getcwd()).resolve())
        config = await ConfigManager.load(cwd)
        paths = await cls.system_paths(cwd, worktree)

        blocks: List[str] = []

        for filepath in paths:
            try:
                content = Path(filepath).read_text(encoding="utf-8")
            except Exception:
                content = ""
            if content:
                blocks.append(f"Instructions from: {filepath}\n{content}")

        urls = [i for i in (config.instructions or []) if i.startswith(("http://", "https://"))]
        if urls:
            try:
                async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
                    async def fetch(url: str) -> str:
                        try:
                            response = await client.get(url)
                        except Exception:
                            return ""
                        if not response.is_success:
                            return ""
                        text = response.text
                        return f"Instructions from: {url}\n{text}" if text else ""

                    fetched = await asyncio.gather(*[fetch(url) for url in urls])
                    for item in fetched:
                        if item:
                            blocks.append(item)
            except Exception:
                # Remote fetch failures should not block sessions.
                pass

        return blocks
