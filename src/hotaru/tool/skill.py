"""Skill tool for loading domain-specific instructions.

This tool allows the AI to load specialized skills that provide
domain-specific instructions, workflows, and resources.

Skills are markdown files with YAML frontmatter that define:
- name: Unique identifier
- description: Brief description

When loaded, a skill injects its content into the conversation,
providing the AI with specialized knowledge for particular tasks.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, List, Optional
from urllib.request import pathname2url

from pydantic import BaseModel, Field

from ..skill import SkillInfo
from ..util.log import Log
from .tool import PermissionSpec, Tool, ToolContext, ToolResult

if TYPE_CHECKING:
    from ..skill import Skill

log = Log.create({"service": "tool.skill"})

# Maximum number of files to list from skill directory
MAX_SKILL_FILES = 10


class SkillParams(BaseModel):
    """Parameters for the Skill tool.

    Attributes:
        name: The name of the skill to load (from available_skills)
    """
    name: str = Field(
        ...,
        description="The name of the skill from available_skills"
    )


def _path_to_file_url(path: str) -> str:
    """Convert a file path to a file:// URL.

    Args:
        path: Absolute file path

    Returns:
        file:// URL string
    """
    return "file:///" + pathname2url(path).lstrip("/")


def _list_skill_files(directory: str, limit: int = MAX_SKILL_FILES) -> List[str]:
    """List files in a skill directory.

    Args:
        directory: Path to the skill directory
        limit: Maximum number of files to return

    Returns:
        List of absolute file paths (excluding SKILL.md)
    """
    results = []
    dir_path = Path(directory)

    if not dir_path.exists():
        return results

    try:
        for item in dir_path.rglob("*"):
            if item.is_file() and item.name != "SKILL.md":
                results.append(str(item.absolute()))
                if len(results) >= limit:
                    break
    except PermissionError:
        pass
    except Exception as e:
        log.warn("error listing skill files", {"directory": directory, "error": str(e)})

    return results


async def _filter_accessible_skills(skills: List[SkillInfo], caller_agent: Optional[str], *, agents: object) -> List[SkillInfo]:
    """Filter skills based on caller agent's skill permission rules."""
    if not caller_agent:
        return skills

    try:
        from ..permission import Permission, PermissionAction

        agent = await agents.get(caller_agent)
        if not agent:
            return skills

        ruleset = Permission.from_config_list(agent.permission)
        filtered: List[SkillInfo] = []
        for skill in skills:
            rule = Permission.evaluate("skill", skill.name, ruleset)
            if rule.action != PermissionAction.DENY:
                filtered.append(skill)
        return filtered
    except Exception as e:
        log.warn("failed to filter skills by agent permissions", {"agent": caller_agent, "error": str(e)})
        return skills


async def build_skill_description(
    caller_agent: Optional[str] = None,
    *,
    skills: Skill,
    agents: object,
) -> str:
    """Build the tool description with available skills."""
    all_skills = await skills.list()
    all_skills = await _filter_accessible_skills(all_skills, caller_agent, agents=agents)

    if not all_skills:
        return (
            "Load a specialized skill that provides domain-specific instructions "
            "and workflows. No skills are currently available."
        )

    # Build skill list
    skill_entries = []
    for skill in all_skills:
        location_url = _path_to_file_url(skill.location)
        skill_entries.extend([
            "  <skill>",
            f"    <name>{skill.name}</name>",
            f"    <description>{skill.description}</description>",
            f"    <location>{location_url}</location>",
            "  </skill>",
        ])

    # Build examples hint
    examples = [f"'{s.name}'" for s in all_skills[:3]]
    hint = f" (e.g., {', '.join(examples)}, ...)" if examples else ""

    description_parts = [
        "Load a specialized skill that provides domain-specific instructions and workflows.",
        "",
        "When you recognize that a task matches one of the available skills listed below, "
        "use this tool to load the full skill instructions.",
        "",
        "The skill will inject detailed instructions, workflows, and access to bundled "
        "resources (scripts, references, templates) into the conversation context.",
        "",
        'Tool output includes a `<skill_content name="...">` block with the loaded content.',
        "",
        "The following skills provide specialized sets of instructions for particular tasks.",
        f"Invoke this tool to load a skill{hint}:",
        "",
        "<available_skills>",
        *skill_entries,
        "</available_skills>",
    ]

    return "\n".join(description_parts)


async def skill_execute(params: SkillParams, ctx: ToolContext) -> ToolResult:
    """Execute the skill tool to load a skill.

    Args:
        params: Tool parameters containing the skill name
        ctx: Tool execution context

    Returns:
        ToolResult with the skill content

    Raises:
        ValueError: If the skill is not found
    """
    skills = ctx.app.skills
    skill = await skills.get(params.name)

    if not skill:
        available = await skills.names()
        available_str = ", ".join(available) if available else "none"
        raise ValueError(
            f'Skill "{params.name}" not found. Available skills: {available_str}'
        )

    # Get the skill directory and base URL
    skill_dir = skill.directory
    base_url = _path_to_file_url(skill_dir)

    # List files in the skill directory
    files = _list_skill_files(skill_dir)
    files_xml = "\n".join(f"<file>{f}</file>" for f in files)

    # Build the output
    output_parts = [
        f'<skill_content name="{skill.name}">',
        f"# Skill: {skill.name}",
        "",
        skill.content.strip(),
        "",
        f"Base directory for this skill: {base_url}",
        "Relative paths in this skill (e.g., scripts/, reference/) are relative to this base directory.",
        "Note: file list is sampled.",
        "",
        "<skill_files>",
        files_xml,
        "</skill_files>",
        "</skill_content>",
    ]

    log.info("loaded skill", {"name": skill.name, "directory": skill_dir})

    return ToolResult(
        title=f"Loaded skill: {skill.name}",
        output="\n".join(output_parts),
        metadata={
            "name": skill.name,
            "dir": skill_dir,
            "directory": skill_dir,
        },
    )


def skill_permissions(params: SkillParams, _ctx: ToolContext) -> list[PermissionSpec]:
    return [
        PermissionSpec(
            permission="skill",
            patterns=[params.name],
            always=[params.name],
            metadata={"skill": params.name},
        )
    ]


# Note: The skill tool description is dynamic and depends on available skills.
# We use a static description here and update it when skills are loaded.
DESCRIPTION = """Load a specialized skill that provides domain-specific instructions and workflows.

When you recognize that a task matches one of the available skills, use this tool
to load the full skill instructions. The skill will inject detailed instructions,
workflows, and access to bundled resources into the conversation context.

Use the 'name' parameter to specify which skill to load.
"""


# Register the tool
SkillTool = Tool.define(
    tool_id="skill",
    description=DESCRIPTION,
    parameters_type=SkillParams,
    permission_fn=skill_permissions,
    execute_fn=skill_execute,
    auto_truncate=False,  # Skill content should not be truncated
)
