"""Skill system for domain-specific instructions and workflows."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from ..core.config import ConfigManager
from ..core.context import ContextNotFoundError
from ..core.global_paths import GlobalPath
from ..core.config_markdown import parse_markdown_config
from ..project import Instance
from ..util.log import Log
from .discovery import Discovery

log = Log.create({"service": "skill"})

# External skill directories to search (compatible with Claude Code and other agents).
# .hotaru is kept for backwards compatibility in hotaru.
EXTERNAL_DIRS = [".claude", ".agents", ".hotaru", ".codex"]

SKILL_FILENAME = "SKILL.md"


@dataclass
class SkillInfo:
    """Information about a loaded skill."""

    name: str
    description: str
    location: str
    content: str
    directory: str


class SkillParseError(Exception):
    """Raised when a skill file cannot be parsed."""

    def __init__(self, path: str, message: str):
        self.path = path
        super().__init__(f"Failed to parse skill at {path}: {message}")


class SkillNotFoundError(Exception):
    """Raised when a requested skill is not found."""

    def __init__(self, name: str, available: Optional[List[str]] = None):
        self.name = name
        self.available = available or []
        msg = f"Skill '{name}' not found"
        if self.available:
            msg += f". Available skills: {', '.join(self.available)}"
        super().__init__(msg)


def _rglob_skills(base: Path, label: str = "skills") -> List[str]:
    """Recursively find SKILL.md files under *base*, handling permission errors."""
    if not base.is_dir():
        return []
    try:
        return [str(f.resolve()) for f in base.rglob(SKILL_FILENAME) if f.is_file()]
    except PermissionError:
        log.warn("permission denied scanning skills", {"directory": str(base)})
    except Exception as e:
        log.error(f"error scanning {label}", {"directory": str(base), "error": str(e)})
    return []


def _find_external_skill_files(root: str) -> List[str]:
    """Find ``skills/**/SKILL.md`` under an external directory root."""
    return _rglob_skills(Path(root) / "skills", "external skills")


def _find_opencode_skill_files(root: str) -> List[str]:
    """Find ``{skill,skills}/**/SKILL.md`` under a config root."""
    root_path = Path(root)
    if not root_path.is_dir():
        return []
    results: List[str] = []
    for dirname in ("skill", "skills"):
        results.extend(_rglob_skills(root_path / dirname, "opencode skills"))
    return results


def _find_all_skill_files(root: str) -> List[str]:
    """Find ``**/SKILL.md`` under a custom or downloaded root."""
    return _rglob_skills(Path(root))


def _load_skill(filepath: str) -> Optional[SkillInfo]:
    """Load a skill from a ``SKILL.md`` file."""
    try:
        parsed = parse_markdown_config(filepath)
    except Exception as e:
        log.error("failed to parse skill frontmatter", {"path": filepath, "error": str(e)})
        return None

    data = parsed.data if isinstance(parsed.data, dict) else {}
    name = data.get("name")
    description = data.get("description")

    if not isinstance(name, str) or not isinstance(description, str):
        log.warn("skill missing required frontmatter fields", {"path": filepath})
        return None

    path = Path(filepath)
    return SkillInfo(
        name=name,
        description=description,
        location=str(path.resolve()),
        content=parsed.content,
        directory=str(path.parent.resolve()),
    )


def _instance_paths() -> Tuple[str, Optional[str]]:
    """Return ``(start_directory, stop_worktree)`` for project scanning."""
    try:
        start = str(Path(Instance.directory()).resolve())
    except ContextNotFoundError:
        start = str(Path(os.getcwd()).resolve())

    try:
        stop = str(Path(Instance.worktree()).resolve())
    except ContextNotFoundError:
        stop = None

    return start, stop


class Skill:
    """Skill discovery and management."""

    def __init__(self) -> None:
        self._cache: Optional[Dict[str, SkillInfo]] = None
        self._directories: Optional[Set[str]] = None

    async def _initialize(self) -> tuple[Dict[str, SkillInfo], Set[str]]:
        if self._cache is not None and self._directories is not None:
            return self._cache, self._directories

        log.info("initializing skills")
        skills: Dict[str, SkillInfo] = {}
        directories: Set[str] = set()

        def add_skill(skill: SkillInfo) -> None:
            if skill.name in skills:
                log.warn(
                    "duplicate skill name",
                    {
                        "name": skill.name,
                        "existing": skills[skill.name].location,
                        "duplicate": skill.location,
                    },
                )
            skills[skill.name] = skill
            directories.add(skill.directory)

        # 1) Scan global external directories first.
        home = Path(GlobalPath.home()).resolve()
        for ext_dir in EXTERNAL_DIRS:
            root = home / ext_dir
            for filepath in _find_external_skill_files(str(root)):
                skill = _load_skill(filepath)
                if skill:
                    add_skill(skill)

        # 2) Scan project external directories from cwd up to worktree.
        start, stop = _instance_paths()
        current = Path(start)
        stop_path = Path(stop) if stop else None
        checked: Set[str] = set()
        while True:
            current_key = str(current.resolve())
            if current_key in checked:
                break
            checked.add(current_key)

            for ext_dir in EXTERNAL_DIRS:
                root = current / ext_dir
                for filepath in _find_external_skill_files(str(root)):
                    skill = _load_skill(filepath)
                    if skill:
                        add_skill(skill)

            if stop_path and current.resolve() == stop_path.resolve():
                break
            parent = current.parent
            if parent == current:
                break
            current = parent

        config = await ConfigManager.get()

        # 3) Scan .opencode roots from config directories.
        seen_roots: Set[str] = set()
        for root in ConfigManager.directories():
            resolved = str(Path(root).resolve())
            if resolved in seen_roots:
                continue
            seen_roots.add(resolved)
            for filepath in _find_opencode_skill_files(resolved):
                skill = _load_skill(filepath)
                if skill:
                    add_skill(skill)

        # 4) Scan custom paths from config.skills.paths.
        try:
            for skill_path in config.skills.paths:
                expanded = skill_path
                if expanded.startswith("~/"):
                    expanded = str(Path(GlobalPath.home()) / expanded[2:])
                resolved = Path(expanded)
                if not resolved.is_absolute():
                    resolved = Path(start) / resolved
                if not resolved.is_dir():
                    log.warn("skill path not found", {"path": str(resolved)})
                    continue
                for filepath in _find_all_skill_files(str(resolved)):
                    skill = _load_skill(filepath)
                    if skill:
                        add_skill(skill)
        except Exception as e:
            log.error("error loading custom skill paths", {"error": str(e)})

        # 5) Download and load remote skills from config.skills.urls.
        try:
            for url in config.skills.urls:
                downloaded_dirs = await Discovery.pull(url)
                for directory in downloaded_dirs:
                    directories.add(str(Path(directory).resolve()))
                    for filepath in _find_all_skill_files(directory):
                        skill = _load_skill(filepath)
                        if skill:
                            add_skill(skill)
        except Exception as e:
            log.error("error loading remote skills", {"error": str(e)})

        log.info("skills initialized", {"count": len(skills)})
        self._cache = skills
        self._directories = directories
        return skills, directories

    async def get(self, name: str) -> Optional[SkillInfo]:
        skills, _ = await self._initialize()
        return skills.get(name)

    async def list(self) -> List[SkillInfo]:
        skills, _ = await self._initialize()
        return list(skills.values())

    async def names(self) -> List[str]:
        skills, _ = await self._initialize()
        return list(skills.keys())

    async def directories(self) -> List[str]:
        _, directories = await self._initialize()
        return list(directories)

    def reset(self) -> None:
        self._cache = None
        self._directories = None
        log.info("skill cache reset")
