"""Skill tool for loading domain-specific instructions.

This tool allows the AI to load specialized skills that provide
domain-specific instructions, workflows, and resources.

Skills are markdown files with YAML frontmatter that define:
- name: Unique identifier
- description: Brief description

When loaded, a skill injects its content into the conversation,
providing the AI with specialized knowledge for particular tasks.
"""

from pathlib import Path
from typing import List, Optional
from urllib.parse import urljoin
from urllib.request import pathname2url

from pydantic import BaseModel, Field

from ..skill import Skill, SkillInfo
from ..util.log import Log
from .tool import Tool, ToolContext, ToolResult

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


async def build_skill_description() -> str:
    """Build the tool description with available skills.

    Returns:
        Tool description string
    """
    skills = await Skill.list()

    if not skills:
        return (
            "Load a specialized skill that provides domain-specific instructions "
            "and workflows. No skills are currently available."
        )

    # Build skill list
    skill_entries = []
    for skill in skills:
        location_url = _path_to_file_url(skill.location)
        skill_entries.extend([
            "  <skill>",
            f"    <name>{skill.name}</name>",
            f"    <description>{skill.description}</description>",
            f"    <location>{location_url}</location>",
            "  </skill>",
        ])

    # Build examples hint
    examples = [f"'{s.name}'" for s in skills[:3]]
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
    skill = await Skill.get(params.name)

    if not skill:
        available = await Skill.names()
        available_str = ", ".join(available) if available else "none"
        raise ValueError(
            f'Skill "{params.name}" not found. Available skills: {available_str}'
        )

    # Request permission to use the skill
    await ctx.ask(
        permission="skill",
        patterns=[params.name],
        always=[params.name],
        metadata={"skill": params.name},
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
            "directory": skill_dir,
        },
    )


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
    execute_fn=skill_execute,
    auto_truncate=False,  # Skill content should not be truncated
)
