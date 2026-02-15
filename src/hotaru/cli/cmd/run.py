"""Run command - execute a single message."""

import asyncio
import json
import platform
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
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
from ...question import Question, QuestionAsked
from ...project import Instance, Project
from ...provider import Provider
from ...session import Message, Session, SessionProcessor, SystemPrompt
from ...tool import ToolRegistry
from ...util.log import Log

# Use legacy_windows=True on Windows to avoid Unicode encoding issues with GBK
_is_windows = platform.system() == "Windows"
console = Console(legacy_windows=_is_windows)
log = Log.create({"service": "cli.run"})


def _normalize_path(path: str) -> str:
    """Normalize a path relative to cwd."""
    if not path:
        return ""
    p = Path(path)
    if p.is_absolute():
        try:
            return str(p.relative_to(Path.cwd()))
        except ValueError:
            return str(p)
    return str(p)


def _print_tool_inline(icon: str, title: str, description: Optional[str] = None):
    """Print a tool invocation inline."""
    suffix = f" [dim]{description}[/dim]" if description else ""
    console.print(f"{icon} {title}{suffix}")


def _print_tool_block(icon: str, title: str, output: Optional[str] = None):
    """Print a tool invocation with output block."""
    console.print()
    console.print(f"{icon} {title}")
    if output and output.strip():
        console.print(output)
    console.print()


async def run_command(
    message: str,
    model: Optional[str] = None,
    agent: Optional[str] = None,
    session_id: Optional[str] = None,
    continue_session: bool = False,
    files: Optional[List[str]] = None,
    show_thinking: bool = False,
    json_output: bool = False,
    yes: bool = False,
) -> None:
    """Execute a single message and display results.

    Args:
        message: Message to send
        model: Model in format provider/model
        agent: Agent name
        session_id: Session ID to continue
        continue_session: Continue last session
        files: Files to attach
        show_thinking: Show thinking blocks
        json_output: Output raw JSON events
        yes: Auto-approve all permission requests
    """
    cwd = str(Path.cwd())

    # Initialize project context
    project, sandbox = await Project.from_directory(cwd)

    init_arguments: Optional[str] = None
    parsed_command = parse_builtin_slash_command(message)
    if parsed_command and parsed_command[0] == "init":
        init_arguments = parsed_command[1]

    expanded = expand_builtin_slash_command(message, sandbox)
    if expanded:
        message = expanded

    log.info("starting run", {
        "project_id": project.id,
        "message_length": len(message),
    })

    # Determine model
    if model:
        provider_id, model_id = Provider.parse_model(model)
    else:
        try:
            provider_id, model_id = await Provider.default_model()
        except RuntimeError as e:
            console.print(f"[red]Error:[/red] {e}")
            console.print()
            console.print("No AI providers are configured. Set an API key:")
            console.print("  export ANTHROPIC_API_KEY=your-key")
            console.print("  export OPENAI_API_KEY=your-key")
            sys.exit(1)

    # Validate model exists
    try:
        model_info = await Provider.get_model(provider_id, model_id)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    # Validate requested agent (if provided)
    requested_agent = agent
    if requested_agent:
        agent_info = await Agent.get(requested_agent)
        if not agent_info:
            console.print(f"[yellow]Warning:[/yellow] Agent '{requested_agent}' not found, using session/default")
            requested_agent = None
        elif agent_info.mode == "subagent":
            console.print(f"[yellow]Warning:[/yellow] Agent '{requested_agent}' is a subagent, using session/default")
            requested_agent = None

    # Get or create session
    if continue_session:
        sessions = await Session.list(project.id)
        if sessions:
            session = sessions[0]
        else:
            initial_agent = requested_agent or await Agent.default_agent()
            session = await Session.create(
                project_id=project.id,
                agent=initial_agent,
                directory=cwd,
                model_id=model_id,
                provider_id=provider_id,
            )
    elif session_id:
        session = await Session.get(session_id)
        if not session:
            console.print(f"[red]Error:[/red] Session '{session_id}' not found")
            sys.exit(1)
    else:
        initial_agent = requested_agent or await Agent.default_agent()
        session = await Session.create(
            project_id=project.id,
            agent=initial_agent,
            directory=cwd,
            model_id=model_id,
            provider_id=provider_id,
        )

    agent_name = requested_agent or session.agent or await Agent.default_agent()
    if agent_name != session.agent:
        updated = await Session.update(session.id, agent=agent_name)
        if updated:
            session = updated

    if not json_output:
        console.print()
        console.print(f"> {agent_name} · {provider_id}/{model_id}")
        console.print()

    # Create user message
    now = int(time.time() * 1000)
    user_message = Message.create_user(
        message_id=Identifier.ascending("message"),
        session_id=session.id,
        text=message,
        created=now,
        agent=agent_name,
    )
    await Session.add_message(session.id, user_message)

    # Create session processor for agentic loop
    is_resuming = continue_session or (session_id is not None)
    processor = SessionProcessor(
        session_id=session.id,
        model_id=model_id,
        provider_id=provider_id,
        agent=agent_name,
        cwd=cwd,
        worktree=sandbox,
    )

    # Load prior conversation history when resuming
    if is_resuming:
        await processor.load_history()

    # Build system prompt
    system_prompt = await SystemPrompt.build_full_prompt(
        model=model_info,
        directory=cwd,
        worktree=sandbox,
        is_git=project.vcs == "git",
    )

    # Track response text
    response_text = ""
    text_buffer = Text()

    # Callbacks for streaming output
    def on_text(text: str):
        nonlocal response_text
        response_text += text
        if not json_output:
            text_buffer.append(text)

    def on_tool_start(tool_name: str, tool_id: str, input_args: Optional[Dict[str, Any]] = None):
        if json_output:
            event = {
                "type": "tool_start",
                "timestamp": int(time.time() * 1000),
                "session_id": session.id,
                "tool": tool_name,
                "tool_id": tool_id,
            }
            print(json.dumps(event), flush=True)
        else:
            console.print(f"\n[dim]> {tool_name}[/dim]", end="")

    def on_tool_end(
        tool_name: str, tool_id: str,
        output: Optional[str], error: Optional[str],
        title: str = "", metadata: Optional[Dict[str, Any]] = None,
    ):
        if json_output:
            event = {
                "type": "tool_end",
                "timestamp": int(time.time() * 1000),
                "session_id": session.id,
                "tool": tool_name,
                "tool_id": tool_id,
                "output": output[:500] if output else None,
                "error": error,
            }
            print(json.dumps(event), flush=True)
        else:
            if error:
                console.print(f" [red]error[/red]")
            else:
                console.print(f" [green]done[/green]")

    # Permission handling — auto-approve with --yes, otherwise terminal prompt
    async def on_permission_asked(payload):
        req = payload.properties
        if yes:
            await Permission.reply(
                req["id"],
                PermissionReply.ONCE,
            )
            return

        permission = req.get("permission", "unknown")
        patterns = req.get("patterns", [])
        metadata = req.get("metadata", {})

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
        msg = None
        if choice == "n":
            msg = await loop.run_in_executor(
                None,
                lambda: Prompt.ask("[dim]Feedback (optional, press Enter to skip)[/dim]", default="")
            )
            msg = msg.strip() or None

        await Permission.reply(
            req["id"],
            PermissionReply(reply_map[choice]),
            msg,
        )

    async def on_question_asked(payload):
        req = payload.properties
        loop = asyncio.get_event_loop()
        try:
            answers: list[list[str]] = []

            console.print()
            console.print("[cyan]Question from assistant:[/cyan]")

            for q in req.get("questions", []):
                prompt = q.get("question", "Question")
                header = q.get("header", "Question")
                options = q.get("options", []) or []
                multiple = bool(q.get("multiple"))
                allow_custom = q.get("custom", True)

                console.print(f"[bold]{header}[/bold]: {prompt}")
                for idx, option in enumerate(options, start=1):
                    label = option.get("label", f"Option {idx}")
                    description = option.get("description", "")
                    console.print(f"  {idx}. {label} - {description}")

                if not options:
                    value = await loop.run_in_executor(
                        None, lambda: Prompt.ask("[bold]Answer[/bold]", default="")
                    )
                    answers.append([value] if value else [])
                    continue

                if multiple:
                    raw = await loop.run_in_executor(
                        None,
                        lambda: Prompt.ask(
                            "[bold]Select options[/bold] [dim](comma-separated indices)[/dim]",
                            default="1",
                        ),
                    )
                    selected: list[str] = []
                    for piece in [p.strip() for p in raw.split(",") if p.strip()]:
                        if piece.isdigit():
                            idx = int(piece)
                            if 1 <= idx <= len(options):
                                selected.append(options[idx - 1].get("label", f"Option {idx}"))
                    if allow_custom and not selected:
                        custom = await loop.run_in_executor(
                            None, lambda: Prompt.ask("[bold]Custom answer[/bold]", default="")
                        )
                        if custom:
                            selected.append(custom)
                    answers.append(selected)
                else:
                    choices = [str(i) for i in range(1, len(options) + 1)]
                    if allow_custom:
                        choices.append("c")
                    selected = await loop.run_in_executor(
                        None,
                        lambda: Prompt.ask(
                            "[bold]Select[/bold]",
                            choices=choices,
                            default="1",
                        ),
                    )
                    if selected == "c":
                        custom = await loop.run_in_executor(
                            None, lambda: Prompt.ask("[bold]Custom answer[/bold]", default="")
                        )
                        answers.append([custom] if custom else [])
                    else:
                        idx = int(selected)
                        answers.append([options[idx - 1].get("label", f"Option {idx}")])

            await Question.reply(req["id"], answers)
        except Exception:
            await Question.reject(req["id"])

    unsub = Bus.subscribe(PermissionAsked, on_permission_asked)
    unsub_question = Bus.subscribe(QuestionAsked, on_question_asked)

    try:
        if json_output:
            # JSON output mode
            result = await processor.process(
                user_message=message,
                system_prompt=system_prompt,
                on_text=on_text,
                on_tool_start=on_tool_start,
                on_tool_end=on_tool_end,
            )

            # Emit final text
            if response_text:
                event = {
                    "type": "text",
                    "timestamp": int(time.time() * 1000),
                    "session_id": session.id,
                    "text": response_text,
                }
                print(json.dumps(event), flush=True)

            if result.error:
                event = {
                    "type": "error",
                    "timestamp": int(time.time() * 1000),
                    "session_id": session.id,
                    "error": result.error,
                }
                print(json.dumps(event), flush=True)
        else:
            # Interactive mode with live display
            with Live(text_buffer, console=console, refresh_per_second=10, transient=True) as live:
                result = await processor.process(
                    user_message=message,
                    system_prompt=system_prompt,
                    on_text=lambda t: (on_text(t), live.update(text_buffer)),
                    on_tool_start=on_tool_start,
                    on_tool_end=on_tool_end,
                )

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

            console.print()

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    finally:
        unsub()
        unsub_question()

    # Create assistant message record
    assistant_message = Message.create_assistant(
        message_id=Identifier.ascending("message"),
        session_id=session.id,
        model_id=model_id,
        provider_id=provider_id,
        cwd=cwd,
        root=sandbox,
        created=now,
        agent=processor.last_assistant_agent(),
    )
    Message.add_text(assistant_message, response_text)
    for tc in (result.tool_calls if result else []):
        Message.add_tool_result(
            assistant_message,
            tool_call_id=tc.id,
            tool_name=tc.name,
            args=tc.input,
            result=tc.output if tc.status == "completed" else (tc.error or ""),
        )
        for attachment in tc.attachments:
            mime = attachment.get("mime") or attachment.get("media_type")
            url = attachment.get("url")
            if not mime or not url:
                continue
            Message.add_file(
                assistant_message,
                media_type=str(mime),
                filename=attachment.get("filename"),
                url=str(url),
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

    log.info("run completed", {"session_id": session.id})
