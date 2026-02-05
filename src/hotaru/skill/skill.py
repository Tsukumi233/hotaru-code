"""Skill system for domain-specific instructions and workflows.

Skills are markdown files (SKILL.md) that provide specialized instructions
for particular tasks. They can include:
- Domain-specific workflows
- Reference materials
- Scripts and templates
- Best practices

Skills are discovered from multiple locations:
1. Global skills: ~/.hotaru/skills/, ~/.claude/skills/, ~/.agents/skills/
2. Project skills: .hotaru/skills/, .claude/skills/, .agents/skills/
3. Custom paths defined in configuration

Each skill is a directory containing a SKILL.md file with YAML frontmatter:
```markdown
---
name: my-skill
description: A brief description of what this skill does
---

# Skill Content

Detailed instructions go here...
```
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml

from ..core.config import ConfigManager
from ..core.global_paths import GlobalPath
from ..project import Instance
from ..util.log import Log

log = Log.create({"service": "skill"})

# External skill directories to search (compatible with Claude Code and other agents)
EXTERNAL_DIRS = [".hotaru", ".claude", ".agents"]

# Skill file name
SKILL_FILENAME = "SKILL.md"


@dataclass
class SkillInfo:
    """Information about a loaded skill.

    Attributes:
        name: Unique identifier for the skill
        description: Brief description of what the skill does
        location: Absolute path to the SKILL.md file
        content: The markdown content (without frontmatter)
        directory: Directory containing the skill
    """
    name: str
    description: str
    location: str
    content: str
    directory: str


class SkillParseError(Exception):
    """Raised when a skill file cannot be parsed.

    Attributes:
        path: Path to the skill file
        message: Error description
    """

    def __init__(self, path: str, message: str):
        self.path = path
        super().__init__(f"Failed to parse skill at {path}: {message}")


class SkillNotFoundError(Exception):
    """Raised when a requested skill is not found.

    Attributes:
        name: Name of the skill that was not found
        available: List of available skill names
    """

    def __init__(self, name: str, available: Optional[List[str]] = None):
        self.name = name
        self.available = available or []
        msg = f"Skill '{name}' not found"
        if self.available:
            msg += f". Available skills: {', '.join(self.available)}"
        super().__init__(msg)


def _parse_frontmatter(content: str) -> tuple[Dict[str, Any], str]:
    """Parse YAML frontmatter from markdown content.

    Frontmatter is delimited by --- at the start and end:
    ```
    ---
    name: my-skill
    description: Does something
    ---

    # Content here
    ```

    Args:
        content: Full markdown content with potential frontmatter

    Returns:
        Tuple of (frontmatter dict, remaining content)

    Raises:
        SkillParseError: If frontmatter is invalid
    """
    # Check for frontmatter delimiter
    if not content.startswith("---"):
        return {}, content

    # Find the closing delimiter
    lines = content.split("\n")
    end_index = -1

    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = i
            break

    if end_index == -1:
        # No closing delimiter, treat as no frontmatter
        return {}, content

    # Extract and parse frontmatter
    frontmatter_lines = lines[1:end_index]
    frontmatter_text = "\n".join(frontmatter_lines)

    try:
        data = yaml.safe_load(frontmatter_text) or {}
    except yaml.YAMLError as e:
        raise SkillParseError("", f"Invalid YAML frontmatter: {e}")

    # Extract remaining content
    remaining_lines = lines[end_index + 1:]
    remaining_content = "\n".join(remaining_lines).strip()

    return data, remaining_content


def _find_skill_files(directory: str, recursive: bool = True) -> List[str]:
    """Find all SKILL.md files in a directory.

    Args:
        directory: Directory to search
        recursive: Whether to search subdirectories

    Returns:
        List of absolute paths to SKILL.md files
    """
    results = []
    dir_path = Path(directory)

    if not dir_path.exists() or not dir_path.is_dir():
        return results

    try:
        if recursive:
            # Search recursively
            for skill_file in dir_path.rglob(SKILL_FILENAME):
                if skill_file.is_file():
                    results.append(str(skill_file.absolute()))
        else:
            # Search only in skills/ subdirectory
            skills_dir = dir_path / "skills"
            if skills_dir.exists():
                for skill_file in skills_dir.rglob(SKILL_FILENAME):
                    if skill_file.is_file():
                        results.append(str(skill_file.absolute()))
    except PermissionError:
        log.warn("permission denied scanning skills", {"directory": directory})
    except Exception as e:
        log.error("error scanning skills", {"directory": directory, "error": str(e)})

    return results


def _load_skill(filepath: str) -> Optional[SkillInfo]:
    """Load a skill from a SKILL.md file.

    Args:
        filepath: Absolute path to the SKILL.md file

    Returns:
        SkillInfo if successful, None if the file is invalid
    """
    try:
        path = Path(filepath)
        content = path.read_text(encoding="utf-8")

        # Parse frontmatter
        try:
            frontmatter, body = _parse_frontmatter(content)
        except SkillParseError as e:
            e.path = filepath
            log.error("failed to parse skill frontmatter", {"path": filepath, "error": str(e)})
            return None

        # Validate required fields
        name = frontmatter.get("name")
        description = frontmatter.get("description", "")

        if not name:
            log.warn("skill missing name field", {"path": filepath})
            return None

        if not isinstance(name, str):
            log.warn("skill name must be a string", {"path": filepath})
            return None

        return SkillInfo(
            name=str(name),
            description=str(description),
            location=filepath,
            content=body,
            directory=str(path.parent),
        )

    except FileNotFoundError:
        log.warn("skill file not found", {"path": filepath})
        return None
    except UnicodeDecodeError:
        log.warn("skill file encoding error", {"path": filepath})
        return None
    except Exception as e:
        log.error("failed to load skill", {"path": filepath, "error": str(e)})
        return None


class Skill:
    """Skill discovery and management.

    Skills are loaded from multiple locations and cached for performance.
    The loading order determines precedence (later overwrites earlier):
    1. Global skills (home directory)
    2. Project skills (working directory)
    3. Custom paths from configuration

    Example:
        # Get all available skills
        skills = await Skill.list()

        # Get a specific skill
        skill = await Skill.get("commit")
        if skill:
            print(skill.content)

        # Get skill directories (for permission rules)
        dirs = await Skill.directories()
    """

    _cache: Optional[Dict[str, SkillInfo]] = None
    _directories: Optional[Set[str]] = None
    _initialized: bool = False

    @classmethod
    async def _initialize(cls) -> tuple[Dict[str, SkillInfo], Set[str]]:
        """Initialize the skill cache by scanning all skill locations.

        Returns:
            Tuple of (skills dict, directories set)
        """
        if cls._cache is not None and cls._directories is not None:
            return cls._cache, cls._directories

        log.info("initializing skills")
        skills: Dict[str, SkillInfo] = {}
        directories: Set[str] = set()

        def add_skill(skill: SkillInfo) -> None:
            """Add a skill to the cache, warning on duplicates."""
            if skill.name in skills:
                log.warn("duplicate skill name", {
                    "name": skill.name,
                    "existing": skills[skill.name].location,
                    "duplicate": skill.location,
                })
            skills[skill.name] = skill
            directories.add(skill.directory)

        # 1. Scan global skill directories (home)
        home = str(Path.home())
        for ext_dir in EXTERNAL_DIRS:
            global_dir = os.path.join(home, ext_dir)
            for filepath in _find_skill_files(global_dir, recursive=False):
                skill = _load_skill(filepath)
                if skill:
                    add_skill(skill)
                    log.info("loaded global skill", {"name": skill.name, "path": filepath})

        # 2. Scan project skill directories
        # Walk up from current directory to find skill directories
        try:
            cwd = os.getcwd()
            current = Path(cwd)

            # Check current directory and parents
            checked = set()
            while current != current.parent:
                if str(current) in checked:
                    break
                checked.add(str(current))

                for ext_dir in EXTERNAL_DIRS:
                    project_dir = current / ext_dir
                    if project_dir.exists():
                        for filepath in _find_skill_files(str(project_dir), recursive=False):
                            skill = _load_skill(filepath)
                            if skill:
                                add_skill(skill)
                                log.info("loaded project skill", {"name": skill.name, "path": filepath})

                current = current.parent
        except Exception as e:
            log.error("error scanning project skills", {"error": str(e)})

        # 3. Scan custom paths from configuration
        try:
            config = await ConfigManager.get()
            custom_paths = getattr(config, "skills", None)
            if custom_paths and hasattr(custom_paths, "paths"):
                for skill_path in custom_paths.paths:
                    # Expand ~ to home directory
                    if skill_path.startswith("~/"):
                        skill_path = os.path.join(home, skill_path[2:])

                    # Make absolute if relative
                    if not os.path.isabs(skill_path):
                        skill_path = os.path.join(os.getcwd(), skill_path)

                    if os.path.isdir(skill_path):
                        for filepath in _find_skill_files(skill_path, recursive=True):
                            skill = _load_skill(filepath)
                            if skill:
                                add_skill(skill)
                                log.info("loaded custom skill", {"name": skill.name, "path": filepath})
        except Exception as e:
            log.error("error loading custom skill paths", {"error": str(e)})

        log.info("skills initialized", {"count": len(skills)})

        cls._cache = skills
        cls._directories = directories
        cls._initialized = True

        return skills, directories

    @classmethod
    async def get(cls, name: str) -> Optional[SkillInfo]:
        """Get a skill by name.

        Args:
            name: The skill name (from frontmatter)

        Returns:
            SkillInfo if found, None otherwise
        """
        skills, _ = await cls._initialize()
        return skills.get(name)

    @classmethod
    async def list(cls) -> List[SkillInfo]:
        """Get all available skills.

        Returns:
            List of SkillInfo objects
        """
        skills, _ = await cls._initialize()
        return list(skills.values())

    @classmethod
    async def names(cls) -> List[str]:
        """Get all skill names.

        Returns:
            List of skill names
        """
        skills, _ = await cls._initialize()
        return list(skills.keys())

    @classmethod
    async def directories(cls) -> List[str]:
        """Get all directories containing skills.

        This is useful for permission rules that need to allow
        access to skill-related files.

        Returns:
            List of directory paths
        """
        _, directories = await cls._initialize()
        return list(directories)

    @classmethod
    def reset(cls) -> None:
        """Reset the skill cache.

        Call this when skills may have changed on disk.
        """
        cls._cache = None
        cls._directories = None
        cls._initialized = False
        log.info("skill cache reset")
