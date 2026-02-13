"""Interactive chat command."""

import asyncio
import platform
import sys
import time
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.prompt import Prompt
from rich.text import Text

from ...agent import Agent
from ...command import (
    expand_builtin_slash_command,
    parse_builtin_slash_command,
    publish_command_executed,
)
from ...core.bus import Bus
from ...core.id import Identifier
from ...permission import Permission, PermissionAsked, PermissionReply
from ...project import Project
from ...provider import Provider
from ...session import Message, Session, SessionProcessor, SystemPrompt
from ...util.log import Log

# Use legacy_windows=True on Windows to avoid Unicode encoding issues
_is_windows = platform.system() == "Windows"
console = Console(legacy_windows=_is_windows)
log = Log.create({"service": "cli.chat"})


async def chat_command(
    model: Optional[str] = None,
    agent: Optional[str] = None,
) -> None:
    """Start an interactive chat session.

    Args:
        model: Model in format provider/model
        agent: Agent name
    """
    cwd = str(Path.cwd())

    # Initialize project context
    project, sandbox = await Project.from_directory(cwd)

    log.info("starting chat", {"project_id": project.id})

    # Determine model
    if model:
        provider_id, model_id = Provider.parse_model(model)
    else:
        try:
            provider_id, model_id = await Provider.default_model()
        except Exception as e:
            console.print(f"[red]Error:[/red] No providers configured. {e}")
            console.print("\nSet an API key via environment variable:")
            console.print("  export ANTHROPIC_API_KEY=your-key")
            console.print("  export OPENAI_API_KEY=your-key")
            sys.exit(1)

    # Validate model exists
    try:
        model_info = await Provider.get_model(provider_id, model_id)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    # Validate agent
    agent_name = agent
    if agent_name:
        agent_info = await Agent.get(agent_name)
        if not agent_info:
            console.print(f"[yellow]Warning:[/yellow] Agent '{agent_name}' not found, using default")
            agent_name = None
        elif agent_info.mode == "subagent":
            console.print(f"[yellow]Warning:[/yellow] Agent '{agent_name}' is a subagent, using default")
            agent_name = None

    if not agent_name:
        agent_name = await Agent.default_agent()

    # Create session
    session = await Session.create(
        project_id=project.id,
        agent=agent_name,
        directory=cwd,
        model_id=model_id,
        provider_id=provider_id,
    )

    # Create session processor
    processor = SessionProcessor(
        session_id=session.id,
        model_id=model_id,
        provider_id=provider_id,
        agent=agent_name,
        cwd=cwd,
        worktree=sandbox,
    )

    # Build system prompt
    system_prompt = await SystemPrompt.build_full_prompt(
        model=model_info,
        directory=cwd,
        worktree=sandbox,
        is_git=project.vcs == "git",
    )

    # Print header
    console.print()
    console.print("[bold]Hotaru Code[/bold] - Interactive Chat")
    console.print(f"Model: [cyan]{provider_id}/{model_id}[/cyan]")
    console.print(f"Agent: [cyan]{agent_name}[/cyan]")
    console.print(f"Session: [dim]{session.id}[/dim]")
    console.print()
    console.print("[dim]Type your message and press Enter. Use Ctrl+C to exit.[/dim]")
    console.print()

    try:
        while True:
            # Get user input
            try:
                user_input = Prompt.ask("[bold cyan]You[/bold cyan]")
            except EOFError:
                break

            if not user_input.strip():
                continue

            # Handle special commands
            if user_input.strip().lower() in ("/exit", "/quit", "/q"):
                break

            if user_input.strip().lower() == "/help":
                console.print()
                console.print("[bold]Commands:[/bold]")
                console.print("  /exit, /quit, /q - Exit chat")
                console.print("  /help - Show this help")
                console.print("  /clear - Clear screen")
                console.print("  /init [extra instructions] - Generate/update AGENTS.md")
                console.print()
                continue

            if user_input.strip().lower() == "/clear":
                console.clear()
                continue

            init_arguments: Optional[str] = None
            parsed_command = parse_builtin_slash_command(user_input)
            if parsed_command and parsed_command[0] == "init":
                init_arguments = parsed_command[1]

            expanded = expand_builtin_slash_command(user_input, sandbox)
            if expanded:
                console.print("[dim]Running /init command...[/dim]")
                user_input = expanded

            # Create user message record
            now = int(time.time() * 1000)
            user_message = Message.create_user(
                message_id=Identifier.ascending("message"),
                session_id=session.id,
                text=user_input,
                created=now,
            )
            await Session.add_message(session.id, user_message)

            # Process with AI
            console.print()
            console.print("[bold green]Assistant[/bold green]")

            response_text = ""
            result = None
            text_buffer = Text()

            def on_text(text: str):
                nonlocal response_text
                response_text += text
                text_buffer.append(text)

            def on_tool_start(tool_name: str, tool_id: str):
                console.print(f"\n[dim]> {tool_name}[/dim]", end="")

            def on_tool_end(tool_name: str, tool_id: str, output: Optional[str], error: Optional[str]):
                if error:
                    console.print(f" [red]error[/red]")
                else:
                    console.print(f" [green]done[/green]")

            try:
                with Live(text_buffer, console=console, refresh_per_second=10, transient=True) as live:
                    # Subscribe to permission events for terminal prompts
                    async def on_permission_asked(payload):
                        req = payload.properties
                        permission = req.get("permission", "unknown")
                        patterns = req.get("patterns", [])
                        metadata = req.get("metadata", {})

                        live.stop()
                        console.print()
                        console.print(f"[yellow]Permission required:[/yellow] {permission}")
                        for p in patterns:
                            console.print(f"  Pattern: {p}")
                        if metadata:
                            for k, v in metadata.items():
                                if isinstance(v, str) and len(v) < 200:
                                    console.print(f"  {k}: {v}")

                        loop = asyncio.get_event_loop()
                        choice = await loop.run_in_executor(
                            None,
                            lambda: Prompt.ask(
                                "[bold]Allow?[/bold] [dim](y=once, a=always, n=reject)[/dim]",
                                choices=["y", "a", "n"],
                                default="y",
                            )
                        )

                        reply_map = {"y": "once", "a": "always", "n": "reject"}
                        message = None
                        if choice == "n":
                            msg = await loop.run_in_executor(
                                None,
                                lambda: Prompt.ask("[dim]Feedback (optional, press Enter to skip)[/dim]", default="")
                            )
                            message = msg.strip() or None

                        await Permission.reply(
                            req["id"],
                            PermissionReply(reply_map[choice]),
                            message,
                        )
                        live.start()

                    unsub = Bus.subscribe(PermissionAsked, on_permission_asked)
                    try:
                        result = await processor.process(
                            user_message=user_input,
                            system_prompt=system_prompt,
                            on_text=lambda t: (on_text(t), live.update(text_buffer)),
                            on_tool_start=on_tool_start,
                            on_tool_end=on_tool_end,
                        )
                    finally:
                        unsub()

                # Print final response
                if response_text:
                    console.print(response_text)

                if result.error:
                    console.print(f"\n[red]Error:[/red] {result.error}")

                # Print usage stats
                if result.usage:
                    input_tokens = result.usage.get("input_tokens", 0)
                    output_tokens = result.usage.get("output_tokens", 0)
                    console.print(f"\n[dim]Tokens: {input_tokens} in / {output_tokens} out[/dim]")

            except Exception as e:
                console.print(f"[red]Error:[/red] {e}")

            # Create assistant message record
            assistant_message = Message.create_assistant(
                message_id=Identifier.ascending("message"),
                session_id=session.id,
                model_id=model_id,
                provider_id=provider_id,
                cwd=cwd,
                root=sandbox,
                created=now,
            )
            if response_text:
                Message.add_text(assistant_message, response_text)
            for tc in (result.tool_calls if result else []):
                Message.add_tool_result(
                    assistant_message,
                    tool_call_id=tc.id,
                    tool_name=tc.name,
                    args=tc.input,
                    result=tc.output if tc.status == "completed" else (tc.error or ""),
                )
            Message.complete(assistant_message, int(time.time() * 1000))
            await Session.add_message(session.id, assistant_message)

            if init_arguments is not None:
                await publish_command_executed(
                    name="init",
                    project_id=project.id,
                    arguments=init_arguments,
                    session_id=session.id,
                    message_id=assistant_message.id,
                )

            console.print()

    except KeyboardInterrupt:
        console.print()
        console.print("[dim]Chat ended.[/dim]")

    log.info("chat ended", {"session_id": session.id})
