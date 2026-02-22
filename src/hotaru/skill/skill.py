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


def _find_external_skill_files(root: str) -> List[str]:
    """Find ``skills/**/SKILL.md`` under an external directory root."""
    root_path = Path(root)
    if not root_path.is_dir():
        return []

    results: List[str] = []
    base = root_path / "skills"
    if not base.is_dir():
        return results

    try:
        for skill_file in base.rglob(SKILL_FILENAME):
            if skill_file.is_file():
                results.append(str(skill_file.resolve()))
    except PermissionError:
        log.warn("permission denied scanning skills", {"directory": root})
    except Exception as e:
        log.error("error scanning external skills", {"directory": root, "error": str(e)})

    return results


def _find_opencode_skill_files(root: str) -> List[str]:
    """Find ``{skill,skills}/**/SKILL.md`` under a config root."""
    root_path = Path(root)
    if not root_path.is_dir():
        return []

    results: List[str] = []
    for dirname in ("skill", "skills"):
        base = root_path / dirname
        if not base.is_dir():
            continue
        try:
            for skill_file in base.rglob(SKILL_FILENAME):
                if skill_file.is_file():
                    results.append(str(skill_file.resolve()))
        except PermissionError:
            log.warn("permission denied scanning skills", {"directory": str(base)})
        except Exception as e:
            log.error("error scanning opencode skills", {"directory": str(base), "error": str(e)})

    return results


def _find_all_skill_files(root: str) -> List[str]:
    """Find ``**/SKILL.md`` under a custom or downloaded root."""
    root_path = Path(root)
    if not root_path.is_dir():
        return []

    results: List[str] = []
    try:
        for skill_file in root_path.rglob(SKILL_FILENAME):
            if skill_file.is_file():
                results.append(str(skill_file.resolve()))
    except PermissionError:
        log.warn("permission denied scanning skills", {"directory": root})
    except Exception as e:
        log.error("error scanning skills", {"directory": root, "error": str(e)})

    return results


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

    _cache: Optional[Dict[str, SkillInfo]] = None
    _directories: Optional[Set[str]] = None

    @classmethod
    async def _initialize(cls) -> tuple[Dict[str, SkillInfo], Set[str]]:
        if cls._cache is not None and cls._directories is not None:
            return cls._cache, cls._directories

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
            for skill_path in (config.skills.paths if config.skills and config.skills.paths else []):
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
            for url in (config.skills.urls if config.skills and config.skills.urls else []):
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
        cls._cache = skills
        cls._directories = directories
        return skills, directories

    @classmethod
    async def get(cls, name: str) -> Optional[SkillInfo]:
        skills, _ = await cls._initialize()
        return skills.get(name)

    @classmethod
    async def list(cls) -> List[SkillInfo]:
        skills, _ = await cls._initialize()
        return list(skills.values())

    @classmethod
    async def names(cls) -> List[str]:
        skills, _ = await cls._initialize()
        return list(skills.keys())

    @classmethod
    async def directories(cls) -> List[str]:
        _, directories = await cls._initialize()
        return list(directories)

    @classmethod
    def reset(cls) -> None:
        cls._cache = None
        cls._directories = None
        log.info("skill cache reset")
