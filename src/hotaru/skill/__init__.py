"""Skill system for domain-specific instructions and workflows.

This module provides the skill discovery and management system that allows
users to define custom instructions for specific tasks.

Example usage:
    from hotaru.skill import Skill

    # List all available skills
    skills = await Skill.list()
    for skill in skills:
        print(f"{skill.name}: {skill.description}")

    # Get a specific skill
    commit_skill = await Skill.get("commit")
    if commit_skill:
        print(commit_skill.content)

Skill files are markdown files named SKILL.md with YAML frontmatter:
    ---
    name: my-skill
    description: Brief description
    ---

    # Detailed Instructions

    Your skill content here...
"""

from .skill import (
    Skill,
    SkillInfo,
    SkillNotFoundError,
    SkillParseError,
)

__all__ = [
    "Skill",
    "SkillInfo",
    "SkillNotFoundError",
    "SkillParseError",
]
