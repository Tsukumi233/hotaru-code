"""Run command - execute a single message."""

import asyncio
import json
import platform
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.prompt import Prompt

from ...command import (
    expand_builtin_slash_command,
    parse_builtin_slash_command,
    publish_command_executed,
)
from ...core.bus import Bus
from ...core.id import Identifier
from ...permission import Permission, PermissionAsked, PermissionReply
from ...question import Question, QuestionAsked
from ...project import Project
from ...session import SessionPrompt
from ...session.orchestration import prepare_prompt_context
from ...session.part_callbacks import create_part_callbacks
from ...session.stream_parts import PartStreamBuilder
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

    try:
        prompt_ctx = await prepare_prompt_context(
            cwd=cwd,
            sandbox=sandbox,
            project_id=project.id,
            project_vcs=project.vcs,
            model=model,
            requested_agent=agent,
            session_id=session_id,
            continue_session=continue_session,
        )
    except RuntimeError as e:
        console.print(f"[red]Error:[/red] {e}")
        console.print()
        console.print("No AI providers are configured. Set an API key:")
        console.print("  export ANTHROPIC_API_KEY=your-key")
        console.print("  export OPENAI_API_KEY=your-key")
        sys.exit(1)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    provider_id = prompt_ctx.provider_id
    model_id = prompt_ctx.model_id
    session = prompt_ctx.session
    agent_name = prompt_ctx.agent_name
    is_resuming = prompt_ctx.is_resuming
    system_prompt = prompt_ctx.system_prompt

    for warning in prompt_ctx.warnings:
        console.print(f"[yellow]Warning:[/yellow] {warning}")

    if not json_output:
        console.print()
        console.print(f"> {agent_name} · {provider_id}/{model_id}")
        console.print()

    assistant_message_id = Identifier.ascending("message")
    part_builder = PartStreamBuilder(session_id=session.id, message_id=assistant_message_id)
    text_parts: Dict[str, Dict[str, Any]] = {}
    reasoning_parts: Dict[str, Dict[str, Any]] = {}
    active_text_part_id: Optional[str] = None
    active_reasoning_part_id: Optional[str] = None
    emitted_tool_calls: set[str] = set()
    prompt_result: Optional[Any] = None

    def _emit_json(event_type: str, payload: Dict[str, Any]) -> None:
        print(
            json.dumps(
                {
                    "type": event_type,
                    "timestamp": int(time.time() * 1000),
                    "session_id": session.id,
                    **payload,
                }
            ),
            flush=True,
        )

    def _render_text_part(part: Dict[str, Any]) -> None:
        text = str(part.get("text") or "").strip()
        if not text:
            return
        if json_output:
            _emit_json("text", {"part": part})
            return
        console.print()
        console.print(text)
        console.print()

    def _render_reasoning_part(part: Dict[str, Any]) -> None:
        if not show_thinking:
            return
        text = str(part.get("text") or "").strip()
        if not text:
            return
        if json_output:
            _emit_json("reasoning", {"part": part})
            return
        console.print()
        console.print(f"[dim][italic]Thinking: {text}[/italic][/dim]")
        console.print()

    def _render_tool_part(part: Dict[str, Any]) -> None:
        if json_output:
            _emit_json("tool_use", {"part": part})
            return
        tool_name = str(part.get("tool") or "tool")
        state = part.get("state") if isinstance(part.get("state"), dict) else {}
        status = str(state.get("status") or "")
        if status == "error":
            console.print(f"\n[dim]> {tool_name}[/dim] [red]error[/red]")
        else:
            console.print(f"\n[dim]> {tool_name}[/dim] [green]done[/green]")

    def _flush_text() -> None:
        nonlocal active_text_part_id
        if not active_text_part_id:
            return
        part = text_parts.get(active_text_part_id)
        active_text_part_id = None
        if part:
            _render_text_part(part)

    def _flush_reasoning() -> None:
        nonlocal active_reasoning_part_id
        if not active_reasoning_part_id:
            return
        part = reasoning_parts.get(active_reasoning_part_id)
        active_reasoning_part_id = None
        if part:
            _render_reasoning_part(part)

    def _handle_part(part: Dict[str, Any]) -> None:
        nonlocal active_text_part_id
        nonlocal active_reasoning_part_id

        part_type = str(part.get("type") or "")
        if part_type != "text":
            _flush_text()
        if part_type != "reasoning":
            _flush_reasoning()

        if part_type == "text":
            part_id = str(part.get("id") or "")
            if not part_id:
                return
            if active_text_part_id and active_text_part_id != part_id:
                _flush_text()
            text_parts[part_id] = dict(part)
            active_text_part_id = part_id
            return

        if part_type == "reasoning":
            part_id = str(part.get("id") or "")
            if not part_id:
                return
            if active_reasoning_part_id and active_reasoning_part_id != part_id:
                _flush_reasoning()
            reasoning_parts[part_id] = dict(part)
            active_reasoning_part_id = part_id
            return

        if part_type == "tool":
            state = part.get("state") if isinstance(part.get("state"), dict) else {}
            status = str(state.get("status") or "")
            if status not in {"completed", "error"}:
                return
            dedupe_key = str(part.get("call_id") or part.get("id") or "")
            if dedupe_key and dedupe_key in emitted_tool_calls:
                return
            if dedupe_key:
                emitted_tool_calls.add(dedupe_key)
            _render_tool_part(part)
            return

        if json_output and part_type == "step-start":
            _emit_json("step_start", {"part": part})
            return
        if json_output and part_type == "step-finish":
            _emit_json("step_finish", {"part": part})

    part_callbacks = create_part_callbacks(part_builder=part_builder, on_part=_handle_part)

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
        prompt_result = await SessionPrompt.prompt(
            session_id=session.id,
            content=message,
            provider_id=provider_id,
            model_id=model_id,
            agent=agent_name,
            cwd=cwd,
            worktree=sandbox,
            system_prompt=system_prompt,
            on_text=part_callbacks.on_text,
            on_tool_update=part_callbacks.on_tool_update,
            on_reasoning_start=part_callbacks.on_reasoning_start,
            on_reasoning_delta=part_callbacks.on_reasoning_delta,
            on_reasoning_end=part_callbacks.on_reasoning_end,
            on_step_start=part_callbacks.on_step_start,
            on_step_finish=part_callbacks.on_step_finish,
            on_patch=part_callbacks.on_patch,
            resume_history=is_resuming,
            assistant_message_id=assistant_message_id,
        )
        result = prompt_result.result

        _flush_text()
        _flush_reasoning()

        if result.error:
            if json_output:
                _emit_json("error", {"error": result.error})
            else:
                console.print(f"\n[red]Error:[/red] {result.error}")

        if not json_output and result.usage:
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

    if init_arguments is not None:
        await publish_command_executed(
            name="init",
            project_id=project.id,
            arguments=init_arguments,
            session_id=session.id,
            message_id=getattr(prompt_result, "assistant_message_id", assistant_message_id),
        )

    log.info("run completed", {"session_id": session.id})
