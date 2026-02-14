"""Agent management CLI commands."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Literal, Optional

import typer
import yaml
from rich.console import Console

from ...agent import Agent
from ...core.global_paths import GlobalPath
from ...project import Project

app = typer.Typer(help="Manage agents")
console = Console()

AgentMode = Literal["all", "primary", "subagent"]

AVAILABLE_TOOLS = [
    "bash",
    "read",
    "write",
    "edit",
    "glob",
    "grep",
    "list",
    "task",
    "skill",
]


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip().lower()).strip("-")
    return slug or "agent"


def _when_to_use(description: str) -> str:
    base = description.strip().rstrip(".")
    return f"Use this agent when {base}."


def _system_prompt(description: str) -> str:
    return "\n".join(
        [
            f"You are a specialized assistant focused on: {description.strip()}",
            "Work methodically, verify assumptions with available tools, and return concise results.",
            "If requirements are unclear, ask focused clarification questions before proceeding.",
        ]
    )


def _disabled_tools(selected: list[str]) -> dict[str, bool]:
    selected_set = {item.strip() for item in selected if item.strip()}
    result: dict[str, bool] = {}
    for tool in AVAILABLE_TOOLS:
        if tool not in selected_set:
            result[tool] = False
    return result


async def _unique_identifier(base: str) -> str:
    existing = {agent.name for agent in await Agent.list()}
    if base not in existing:
        return base

    index = 2
    while f"{base}-{index}" in existing:
        index += 1
    return f"{base}-{index}"


@app.command("create")
def create_agent(
    path: Optional[str] = typer.Option(None, "--path", help="Directory path to generate the agent file"),
    description: Optional[str] = typer.Option(None, "--description", help="What the agent should do"),
    mode: Optional[AgentMode] = typer.Option(None, "--mode", help="Agent mode"),
    tools: Optional[str] = typer.Option(
        None,
        "--tools",
        help=f"Comma-separated list of enabled tools (default: all). Available: {', '.join(AVAILABLE_TOOLS)}",
    ),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Model in format provider/model"),
) -> None:
    """Create a markdown agent config file."""
    cwd = str(Path.cwd())

    target_dir: Path
    if path:
        target_dir = Path(path).expanduser().resolve()
    else:
        project, _ = asyncio.run(Project.from_directory(cwd))
        if project.vcs == "git":
            use_project = typer.confirm("Save agent in current project (.opencode/agents)?", default=True)
            if use_project:
                target_dir = Path(project.worktree).resolve() / ".opencode" / "agents"
            else:
                target_dir = Path(GlobalPath.config()).resolve() / "agents"
        else:
            target_dir = Path(GlobalPath.config()).resolve() / "agents"

    if not description:
        description = typer.prompt("Description", prompt_suffix=": ").strip()
    if not description:
        raise typer.Exit(1)

    if not mode:
        mode = typer.prompt(
            "Mode (all/primary/subagent)",
            default="all",
        ).strip().lower()  # type: ignore[assignment]
        if mode not in {"all", "primary", "subagent"}:
            console.print("[red]Invalid mode[/red]")
            raise typer.Exit(1)

    selected_tools: list[str]
    if tools is None:
        selected_tools = AVAILABLE_TOOLS.copy()
    elif not tools.strip():
        selected_tools = AVAILABLE_TOOLS.copy()
    else:
        selected_tools = [item.strip() for item in tools.split(",") if item.strip()]

    frontmatter: dict[str, object] = {
        "description": _when_to_use(description),
        "mode": mode,
    }
    if model:
        frontmatter["model"] = model
    disabled_tools = _disabled_tools(selected_tools)
    if disabled_tools:
        frontmatter["tools"] = disabled_tools

    identifier = asyncio.run(_unique_identifier(_slugify(description)))
    body = _system_prompt(description)

    target_dir.mkdir(parents=True, exist_ok=True)
    filepath = target_dir / f"{identifier}.md"
    if filepath.exists():
        console.print(f"[red]Agent file already exists:[/red] {filepath}")
        raise typer.Exit(1)

    yaml_text = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=False).strip()
    content = f"---\n{yaml_text}\n---\n{body}\n"
    filepath.write_text(content, encoding="utf-8")

    console.print(str(filepath))


@app.command("list")
def list_agents() -> None:
    """List agents with mode and visibility."""

    async def _list() -> None:
        agents = await Agent.list()
        for agent in agents:
            visibility = "hidden" if agent.hidden else "visible"
            native = "native" if agent.native else "custom"
            console.print(f"{agent.name} ({agent.mode}, {visibility}, {native})")

    asyncio.run(_list())
