"""CLI entry point for Hotaru Code.

This module provides the main CLI interface for Hotaru Code.
Running `hotaru` without arguments launches the TUI (Terminal User Interface).
"""

import asyncio
import os
import sys
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console

from .. import __version__
from ..runtime.logging import bootstrap_logging
from .cmd.agent import app as agent_app
from .cmd.debug import app as debug_app
from .cmd.mcp import app as mcp_app

app = typer.Typer(
    name="hotaru",
    help="Hotaru Code - AI-powered coding assistant",
    no_args_is_help=False,  # TUI is the default when no args
    add_completion=False,
    invoke_without_command=True,  # Allow callback to run without subcommand
)
app.add_typer(agent_app, name="agent", help="Manage agents")
app.add_typer(debug_app, name="debug", help="Debugging utilities")
app.add_typer(mcp_app, name="mcp", help="Manage MCP servers")

console = Console()


def version_callback(value: bool):
    """Print version and exit."""
    if value:
        console.print(f"hotaru-code {__version__}")
        raise typer.Exit()


def directory_callback(ctx: typer.Context, value: Optional[str]) -> Optional[str]:
    """Change working directory if specified."""
    if value:
        target_dir = Path(value).resolve()
        if not target_dir.exists():
            console.print(f"[red]Error:[/red] Directory does not exist: {target_dir}")
            raise typer.Exit(1)
        if not target_dir.is_dir():
            console.print(f"[red]Error:[/red] Not a directory: {target_dir}")
            raise typer.Exit(1)

        # Load config from current directory BEFORE changing
        # This preserves provider configurations from the original project
        import asyncio
        from ..core.config import ConfigManager
        from ..provider import Provider

        async def preload_config():
            await ConfigManager.load()
            await Provider.list()

        asyncio.run(preload_config())

        os.chdir(target_dir)
    return value


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        None,
        "--version",
        "-v",
        callback=version_callback,
        is_eager=True,
        help="Show version and exit",
    ),
    directory: Optional[str] = typer.Option(
        None,
        "--directory",
        "-d",
        callback=directory_callback,
        is_eager=True,
        help="Working directory for the session",
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        "-m",
        help="Model to use in format provider/model",
    ),
    agent: Optional[str] = typer.Option(
        None,
        "--agent",
        "-a",
        help="Agent to use",
    ),
    session: Optional[str] = typer.Option(
        None,
        "--session",
        "-s",
        help="Session ID to continue",
    ),
    continue_session: bool = typer.Option(
        False,
        "--continue",
        "-c",
        help="Continue the last session",
    ),
    prompt: Optional[str] = typer.Option(
        None,
        "--prompt",
        "-p",
        help="Initial prompt to send",
    ),
):
    """Hotaru Code - AI-powered coding assistant.

    Running without a subcommand launches the interactive TUI.
    """
    if ctx.invoked_subcommand and ctx.invoked_subcommand not in {"run", "tui", "web"}:
        bootstrap_logging(mode="cli")

    # If a subcommand was invoked, don't run TUI
    if ctx.invoked_subcommand is not None:
        return

    # Launch TUI as default behavior
    from .cmd.tui import tui_command

    bootstrap_logging(mode="tui")
    tui_command(
        model=model,
        agent=agent,
        session_id=session,
        continue_session=continue_session,
        prompt=prompt,
    )


@app.command()
def run(
    message: List[str] = typer.Argument(
        None,
        help="Message to send to the AI",
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        "-m",
        help="Model to use in format provider/model",
    ),
    agent: Optional[str] = typer.Option(
        None,
        "--agent",
        "-a",
        help="Agent to use",
    ),
    session: Optional[str] = typer.Option(
        None,
        "--session",
        "-s",
        help="Session ID to continue",
    ),
    continue_session: bool = typer.Option(
        False,
        "--continue",
        "-c",
        help="Continue the last session",
    ),
    file: Optional[List[str]] = typer.Option(
        None,
        "--file",
        "-f",
        help="File(s) to attach to message",
    ),
    thinking: bool = typer.Option(
        False,
        "--thinking",
        help="Show thinking blocks",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output raw JSON events",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Auto-approve all permission requests",
    ),
):
    """Run hotaru with a message."""
    from .cmd.run import run_command

    bootstrap_logging(mode="run")

    # Combine message parts
    text = " ".join(message) if message else ""

    # Read from stdin if not a TTY
    if not sys.stdin.isatty():
        stdin_text = sys.stdin.read()
        if stdin_text:
            text = f"{text}\n{stdin_text}" if text else stdin_text

    if not text.strip():
        console.print("[red]Error:[/red] You must provide a message")
        raise typer.Exit(1)

    # Run the command
    asyncio.run(run_command(
        message=text,
        model=model,
        agent=agent,
        session_id=session,
        continue_session=continue_session,
        files=file,
        show_thinking=thinking,
        json_output=json_output,
        yes=yes,
    ))


@app.command()
def web(
    host: str = typer.Option(
        "127.0.0.1",
        "--host",
        help="Host to bind web server to",
    ),
    port: int = typer.Option(
        4096,
        "--port",
        help="Port to bind web server to",
    ),
    open_browser: bool = typer.Option(
        False,
        "--open",
        help="Open the browser after server startup",
    ),
    log_level: Optional[str] = typer.Option(
        None,
        "--log-level",
        help="Log level: debug, info, warn, error",
    ),
    log_format: Optional[str] = typer.Option(
        None,
        "--log-format",
        help="Log format: kv, json, pretty",
    ),
    access_log: bool = typer.Option(
        True,
        "--access-log/--no-access-log",
        help="Enable HTTP access logs",
    ),
):
    """Start Hotaru WebUI server."""
    from .cmd.web import web_command

    web_command(
        host=host,
        port=port,
        open_browser=open_browser,
        log_level=log_level,
        log_format=log_format,
        access_log=access_log,
    )


@app.command()
def config(
    show: bool = typer.Option(
        False,
        "--show",
        help="Show current configuration",
    ),
    path: bool = typer.Option(
        False,
        "--path",
        help="Show configuration file path",
    ),
):
    """Manage configuration."""
    from ..core.global_paths import GlobalPath

    if path:
        console.print(GlobalPath.config())
        return

    if show:
        import json
        from ..core.config import ConfigManager

        async def show_config():
            config = await ConfigManager.get()
            console.print_json(json.dumps(config.model_dump(), indent=2, default=str))

        asyncio.run(show_config())
        return

    console.print("Use --show to display configuration or --path to show config path")


@app.command()
def providers():
    """List available AI providers."""
    from ..provider import Provider

    async def list_providers():
        providers = await Provider.list()

        if not providers:
            console.print("[yellow]No providers configured[/yellow]")
            console.print("Set API keys via environment variables or configuration file")
            return

        console.print(f"\n[bold]Available Providers ({len(providers)})[/bold]\n")

        for provider_id, provider in sorted(providers.items()):
            model_count = len(provider.models)
            source_info = f"[dim]({provider.source.value})[/dim]" if provider.source else ""
            console.print(f"  [cyan]{provider_id}[/cyan] - {provider.name} ({model_count} models) {source_info}")

            # Show base URL if custom
            base_url = provider.options.get("baseURL")
            if base_url:
                console.print(f"    [dim]Base URL: {base_url}[/dim]")

            # Show a few models
            models = list(provider.models.keys())[:3]
            for model_id in models:
                console.print(f"    - {model_id}")
            if len(provider.models) > 3:
                console.print(f"    ... and {len(provider.models) - 3} more")

        console.print()

    asyncio.run(list_providers())


@app.command()
def agents():
    """List available agents."""
    from ..runtime import AppContext

    async def list_agents():
        ctx = AppContext()
        try:
            agents = await ctx.agents.list()

            console.print(f"\n[bold]Available Agents ({len(agents)})[/bold]\n")

            for agent in agents:
                if agent.hidden:
                    continue

                mode_badge = {
                    "primary": "[green]primary[/green]",
                    "subagent": "[blue]subagent[/blue]",
                    "all": "[yellow]all[/yellow]",
                }.get(agent.mode, agent.mode)

                console.print(f"  [cyan]{agent.name}[/cyan] {mode_badge}")
                if agent.description:
                    desc = agent.description[:80] + "..." if len(agent.description) > 80 else agent.description
                    console.print(f"    {desc}")

            console.print()
        finally:
            await ctx.shutdown()

    asyncio.run(list_agents())


@app.command()
def sessions(
    limit: int = typer.Option(
        10,
        "--limit",
        "-n",
        help="Number of sessions to show",
    ),
):
    """List recent sessions."""
    from ..session import Session
    from ..project import Project

    async def list_sessions():
        # Get project from current directory
        project, _ = await Project.from_directory(str(Path.cwd()))

        sessions = await Session.list(project.id)

        if not sessions:
            console.print("[yellow]No sessions found[/yellow]")
            return

        console.print(f"\n[bold]Recent Sessions[/bold]\n")

        for session in sessions[:limit]:
            title = session.title or "(untitled)"
            agent = session.agent
            console.print(f"  [cyan]{session.id}[/cyan] - {title}")
            console.print(f"    Agent: {agent}")

        if len(sessions) > limit:
            console.print(f"\n  ... and {len(sessions) - limit} more")

        console.print()

    asyncio.run(list_sessions())


@app.command()
def tui(
    model: Optional[str] = typer.Option(
        None,
        "--model",
        "-m",
        help="Model to use in format provider/model",
    ),
    agent: Optional[str] = typer.Option(
        None,
        "--agent",
        "-a",
        help="Agent to use",
    ),
    session: Optional[str] = typer.Option(
        None,
        "--session",
        "-s",
        help="Session ID to continue",
    ),
    continue_session: bool = typer.Option(
        False,
        "--continue",
        "-c",
        help="Continue the last session",
    ),
    prompt: Optional[str] = typer.Option(
        None,
        "--prompt",
        "-p",
        help="Initial prompt to send",
    ),
):
    """Start the interactive Terminal User Interface.

    This is the default command when running `hotaru` without arguments.
    The TUI provides a rich interactive experience with:
    - Session management
    - Real-time streaming responses
    - Tool execution visualization
    - Keyboard shortcuts and commands
    """
    from .cmd.tui import tui_command

    bootstrap_logging(mode="tui")
    tui_command(
        model=model,
        agent=agent,
        session_id=session,
        continue_session=continue_session,
        prompt=prompt,
    )


if __name__ == "__main__":
    app()
