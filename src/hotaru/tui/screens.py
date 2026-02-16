"""Screens for TUI application."""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, ScrollableContainer
from textual.screen import Screen
from textual.widgets import Static

from .commands import CommandRegistry, create_default_commands
from .context import use_kv, use_local, use_route, use_sdk, use_sync
from .context.route import HomeRoute, PromptInfo, SessionRoute
from .dialogs import InputDialog, PermissionDialog, SelectDialog
from .input_parsing import enrich_content_with_file_references
from .widgets import (
    AppFooter,
    AssistantTextPart,
    Logo,
    MessageBubble,
    PromptHints,
    PromptInput,
    PromptMeta,
    SessionHeaderBar,
    SlashCommandItem,
    Spinner,
    StatusBar,
    ToolDisplay,
)


@dataclass
class AssistantTurnState:
    """Mounted widgets for the currently streaming assistant turn."""

    text_parts: Dict[str, AssistantTextPart] = field(default_factory=dict)
    tool_widgets: Dict[str, ToolDisplay] = field(default_factory=dict)


def _build_slash_commands(registry: CommandRegistry) -> List[SlashCommandItem]:
    """Build slash command items from registry."""
    items: List[SlashCommandItem] = []
    for cmd in registry.list_commands():
        if not cmd.slash_name:
            continue

        description = cmd.availability_reason if not cmd.enabled else ""
        items.append(
            SlashCommandItem(
                id=cmd.id,
                trigger=cmd.slash_name,
                title=cmd.title,
                description=description,
                keybind=cmd.keybind,
                type="builtin",
            )
        )

        for alias in cmd.slash_aliases:
            items.append(
                SlashCommandItem(
                    id=cmd.id,
                    trigger=alias,
                    title=cmd.title,
                    description=f"Alias for /{cmd.slash_name}",
                    keybind=cmd.keybind,
                    type="builtin",
                )
            )
    return items


class HomeScreen(Screen):
    """Home screen with logo and prompt."""

    BINDINGS = [
        Binding("ctrl+p", "command_palette", "Commands"),
        Binding("ctrl+s", "session_list", "Sessions"),
        Binding("tab", "cycle_agent", "Agents", show=False),
        Binding("ctrl+c", "quit", "Quit", priority=True),
    ]

    CSS = """
    HomeScreen {
        layout: vertical;
    }

    #home-body {
        align: center middle;
        height: 1fr;
    }

    #home-center {
        width: 80;
        height: auto;
        align: center middle;
    }

    #logo-container {
        width: 100%;
        height: auto;
        align: center middle;
        padding: 2 0;
    }

    #prompt-container {
        width: 100%;
        height: auto;
        padding: 1 0;
    }

    #prompt-footer {
        width: 100%;
        height: auto;
        padding: 0;
    }

    PromptInput {
        width: 100%;
    }
    """

    def __init__(self, initial_prompt: Optional[str] = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.initial_prompt = initial_prompt
        self._command_registry = CommandRegistry()
        for cmd in create_default_commands():
            self._command_registry.register(cmd)

    def compose(self) -> ComposeResult:
        from .. import __version__

        slash_commands = _build_slash_commands(self._command_registry)

        # Main body (centered)
        yield Container(
            Container(
                Container(Logo(), id="logo-container"),
                Container(
                    PromptInput(
                        placeholder="What would you like to do?",
                        commands=slash_commands,
                        id="prompt-input",
                    ),
                    id="prompt-container",
                ),
                Container(
                    PromptMeta(id="prompt-meta"),
                    PromptHints(id="prompt-hints"),
                    id="prompt-footer",
                ),
                id="home-center",
            ),
            id="home-body",
        )

        # Footer bar
        sdk = use_sdk()
        sync = use_sync()
        mcp_data = sync.data.mcp
        mcp_connected = sum(1 for v in mcp_data.values() if v.get("status") == "connected")
        mcp_error = any(v.get("status") == "failed" for v in mcp_data.values())

        yield AppFooter(
            directory=sdk.cwd,
            mcp_connected=mcp_connected,
            mcp_error=mcp_error,
            version=__version__,
            id="home-footer",
        )

    def on_mount(self) -> None:
        prompt = self.query_one("#prompt-input", PromptInput)
        prompt.focus()
        if self.initial_prompt:
            prompt.value = self.initial_prompt
        self._refresh_prompt_meta()

    def _refresh_prompt_meta(self) -> None:
        local = use_local()
        meta = self.query_one("#prompt-meta", PromptMeta)
        agent_info = local.agent.current()
        meta.agent = agent_info.get("name", "build")

        model_selection = local.model.current()
        if model_selection:
            meta.model_name = model_selection.model_id
            meta.provider = model_selection.provider_id
        else:
            meta.model_name = ""
            meta.provider = ""
        meta.refresh()

    def on_prompt_input_submitted(self, event: PromptInput.Submitted) -> None:
        if self.app.execute_slash_command(event.value, source="slash"):
            return
        use_route().navigate(
            SessionRoute(initial_prompt=PromptInfo(input=event.value))
        )

    def on_prompt_input_slash_command_selected(
        self, event: PromptInput.SlashCommandSelected
    ) -> None:
        self.app.execute_command(event.command_id, source="slash")

    def action_command_palette(self) -> None:
        self.app.action_command_palette()

    def action_session_list(self) -> None:
        self.app.action_session_list()

    def action_cycle_agent(self) -> None:
        local = use_local()
        local.agent.move(1)
        self._refresh_prompt_meta()

    def action_quit(self) -> None:
        self.app.exit()


class SessionScreen(Screen):
    """Session screen with message history and prompt input."""

    BINDINGS = [
        Binding("ctrl+p", "command_palette", "Commands"),
        Binding("ctrl+n", "new_session", "New"),
        Binding("ctrl+s", "session_list", "Sessions"),
        Binding("ctrl+z", "undo", "Undo"),
        Binding("ctrl+y", "redo", "Redo"),
        Binding("tab", "cycle_agent", "Agents", show=False),
        Binding("escape", "go_home", "Home"),
        Binding("pageup", "page_up", "Page Up", show=False),
        Binding("pagedown", "page_down", "Page Down", show=False),
        Binding("ctrl+c", "quit", "Quit", priority=True),
    ]

    CSS = """
    SessionScreen {
        layout: vertical;
    }

    #session-header {
        height: auto;
        min-height: 3;
        padding: 1 2;
        background: $surface;
    }

    #messages-container {
        height: 1fr;
        padding: 1 2;
    }

    #prompt-container {
        height: auto;
        min-height: 3;
        padding: 1 2;
        background: $surface;
    }

    #prompt-footer {
        height: auto;
        padding: 0;
    }

    .message {
        margin-bottom: 1;
    }

    .user-message {
        border-left: thick $accent;
        padding-left: 1;
    }

    .assistant-message {
        padding-left: 2;
    }

    .tool-display {
        padding-left: 3;
        color: $text-muted;
    }

    PromptInput {
        width: 100%;
    }
    """

    def __init__(
        self,
        session_id: Optional[str] = None,
        initial_message: Optional[str] = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.session_id = session_id
        self.initial_message = initial_message
        self._active_turn: Optional[AssistantTurnState] = None
        self._loading_spinner: Optional[Spinner] = None
        self._uses_tool_part_updates: bool = False
        self._legacy_tool_parts: Dict[str, Dict[str, Any]] = {}
        self._show_tool_details = bool(use_kv().get("tool_details_visibility", True))
        self._command_registry = CommandRegistry()
        for cmd in create_default_commands():
            self._command_registry.register(cmd)

    def compose(self) -> ComposeResult:
        from .. import __version__

        slash_commands = _build_slash_commands(self._command_registry)

        # Session header
        yield SessionHeaderBar(id="session-header")

        # Messages
        yield ScrollableContainer(id="messages-container")

        # Prompt area
        yield Container(
            PromptInput(
                placeholder="Type your message...",
                commands=slash_commands,
                id="prompt-input",
            ),
            id="prompt-container",
        )

        # Agent/model info + hints
        yield Container(
            PromptMeta(id="prompt-meta"),
            PromptHints(id="prompt-hints"),
            id="prompt-footer",
        )

        # Footer bar
        sdk = use_sdk()
        sync = use_sync()
        mcp_data = sync.data.mcp
        mcp_connected = sum(1 for v in mcp_data.values() if v.get("status") == "connected")
        mcp_error = any(v.get("status") == "failed" for v in mcp_data.values())
        lsp_count = len(sync.data.lsp)

        yield AppFooter(
            directory=sdk.cwd,
            mcp_connected=mcp_connected,
            mcp_error=mcp_error,
            lsp_count=lsp_count,
            show_lsp=True,
            version=__version__,
            id="session-footer",
        )

    def on_mount(self) -> None:
        prompt = self.query_one("#prompt-input", PromptInput)
        prompt.focus()
        self._refresh_header()

        if self.session_id:
            self.run_worker(self._load_session_history(), exclusive=False)

        if self.initial_message:
            self.call_after_refresh(lambda: self._send_message(self.initial_message or ""))

    async def _load_session_history(self) -> None:
        """Load and render historical messages for an existing session."""
        if not self.session_id:
            return
        self._show_tool_details = bool(use_kv().get("tool_details_visibility", True))

        sync = use_sync()
        if not sync.is_session_synced(self.session_id):
            await sync.sync_session(self.session_id)

        container = self.query_one("#messages-container", ScrollableContainer)
        container.remove_children()
        self._active_turn = None
        self._loading_spinner = None

        for message in sync.get_messages(self.session_id):
            await self._mount_message_from_history(message, container)

        container.scroll_end(animate=False)
        self._refresh_header()

    async def _mount_message_from_history(
        self, message: Dict[str, Any], container: ScrollableContainer
    ) -> None:
        """Render a persisted message in the message timeline."""
        role = message.get("role", "")
        if role == "user":
            text = self._extract_text(message)
            await container.mount(
                MessageBubble(
                    content=text,
                    role="user",
                    classes="message user-message",
                )
            )
            return

        info = message.get("info", {})
        agent = use_local().agent.current().get("name", "assistant")
        if isinstance(info, dict):
            info_agent = info.get("agent")
            if isinstance(info_agent, str) and info_agent:
                agent = info_agent
        await container.mount(
            MessageBubble(
                content="",
                role="assistant",
                agent=agent,
                classes="message assistant-message",
            )
        )

        parts = message.get("parts", [])
        for idx, part in enumerate(parts):
            if not isinstance(part, dict):
                continue

            part_type = part.get("type")
            if part_type in ("text", "reasoning"):
                text = part.get("text", "")
                if text:
                    await container.mount(
                        AssistantTextPart(
                            content=text,
                            part_id=f"history-{message.get('id', '')}-{idx}",
                            classes="message assistant-message",
                        )
                    )
            elif part_type == "tool":
                if self._should_hide_tool_part(part):
                    continue
                await container.mount(
                    ToolDisplay(
                        part=part,
                        show_details=self._show_tool_details,
                        on_open_session=self._open_task_session,
                        classes="message tool-display",
                    )
                )
            elif part_type == "step-start":
                await container.mount(
                    AssistantTextPart(
                        content="[Step started]",
                        part_id=f"history-{message.get('id', '')}-{idx}",
                        classes="message assistant-message",
                    )
                )
            elif part_type == "step-finish":
                reason = str(part.get("reason") or "completed")
                await container.mount(
                    AssistantTextPart(
                        content=f"[Step finished: {reason}]",
                        part_id=f"history-{message.get('id', '')}-{idx}",
                        classes="message assistant-message",
                    )
                )
            elif part_type == "patch":
                files = part.get("files")
                file_count = len(files) if isinstance(files, list) else 0
                await container.mount(
                    AssistantTextPart(
                        content=f"[Patch changed {file_count} file(s)]",
                        part_id=f"history-{message.get('id', '')}-{idx}",
                        classes="message assistant-message",
                    )
                )

    def _extract_text(self, message: Dict[str, Any]) -> str:
        parts = message.get("parts", [])
        chunks: List[str] = []
        for part in parts:
            if isinstance(part, dict) and part.get("type") == "text":
                text = part.get("text")
                if isinstance(text, str):
                    chunks.append(text)
        return "".join(chunks)

    def _stringify_output(self, output: Any) -> str:
        if output is None:
            return ""
        if isinstance(output, str):
            return output
        return str(output)

    def _refresh_header(self) -> None:
        """Refresh session title and context info."""
        header = self.query_one("#session-header", SessionHeaderBar)

        # Title
        if self.session_id:
            sync = use_sync()
            session = sync.get_session(self.session_id)
            if session:
                header.title = session.get("title", "Untitled")
            else:
                header.title = f"Session {self.session_id[:8]}"
        else:
            header.title = "New Session"

        # Context info (token count + cost) from messages
        if self.session_id:
            sync = use_sync()
            messages = sync.get_messages(self.session_id)
            total_tokens = 0
            total_cost = 0.0
            for msg in messages:
                if msg.get("role") == "assistant":
                    info = msg.get("info", {})
                    if isinstance(info, dict):
                        tokens = info.get("tokens", {})
                        if isinstance(tokens, dict):
                            total_tokens += int(tokens.get("input", 0) or 0)
                            total_tokens += int(tokens.get("output", 0) or 0)
                            total_tokens += int(tokens.get("reasoning", 0) or 0)
                        total_cost += float(info.get("cost", 0.0) or 0.0)
            if total_tokens > 0:
                header.context_info = f"{total_tokens:,}"
            else:
                header.context_info = ""
            if total_cost > 0:
                header.cost = f"${total_cost:.4f}"
            else:
                header.cost = ""
        else:
            header.context_info = ""
            header.cost = ""

        header.refresh()
        self._refresh_prompt_meta()

    def _refresh_prompt_meta(self) -> None:
        """Refresh agent/model info below the prompt."""
        local = use_local()
        meta = self.query_one("#prompt-meta", PromptMeta)
        agent_info = local.agent.current()
        meta.agent = agent_info.get("name", "build")

        model_selection = local.model.current()
        if model_selection:
            meta.model_name = model_selection.model_id
            meta.provider = model_selection.provider_id
        else:
            meta.model_name = ""
            meta.provider = ""
        meta.refresh()

    def on_prompt_input_submitted(self, event: PromptInput.Submitted) -> None:
        if self.app.execute_slash_command(event.value, source="slash"):
            return
        self._send_message(event.value)

    def on_prompt_input_slash_command_selected(
        self, event: PromptInput.SlashCommandSelected
    ) -> None:
        self.app.execute_command(event.command_id, source="slash")

    def _send_message(self, content: str) -> None:
        content = content.strip()
        if not content:
            return

        if self.session_id:
            self.app.clear_session_redo(self.session_id)

        if content.startswith("!"):
            command = content[1:].strip()
            if not command:
                self.app.notify("Shell command cannot be empty.", severity="warning")
                return
            self._send_shell_command(raw_input=content, command=command)
            return

        container = self.query_one("#messages-container", ScrollableContainer)
        container.mount(
            MessageBubble(
                content=content,
                role="user",
                classes="message user-message",
            )
        )
        container.scroll_end()

        self._loading_spinner = Spinner("Thinking...")
        container.mount(self._loading_spinner)

        prompt = self.query_one("#prompt-input", PromptInput)
        prompt.disabled = True

        self.run_worker(
            self._send_message_async(content, container),
            exclusive=True,
        )

    def _send_shell_command(self, raw_input: str, command: str) -> None:
        """Execute a local shell command in session view."""
        container = self.query_one("#messages-container", ScrollableContainer)
        container.mount(
            MessageBubble(
                content=raw_input,
                role="user",
                classes="message user-message",
            )
        )
        container.scroll_end()

        self._loading_spinner = Spinner("Running shell command...")
        container.mount(self._loading_spinner)

        prompt = self.query_one("#prompt-input", PromptInput)
        prompt.disabled = True

        self.run_worker(
            self._run_shell_command_async(command, container),
            exclusive=True,
        )

    async def _run_shell_command_async(
        self,
        command: str,
        container: ScrollableContainer,
    ) -> None:
        """Run a shell command and render output as assistant content."""
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=use_sdk().cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            output = (stdout or b"").decode("utf-8", errors="replace").strip()
            err = (stderr or b"").decode("utf-8", errors="replace").strip()
            combined = "\n".join(part for part in [output, err] if part)
            exit_code = proc.returncode or 0

            await self._remove_spinner()
            await container.mount(
                MessageBubble(
                    content="",
                    role="assistant",
                    agent="shell",
                    classes="message assistant-message",
                )
            )

            rendered_output = combined if combined else "(no output)"
            rendered = (
                "```text\n"
                f"$ {command}\n"
                f"{rendered_output}\n"
                f"[exit code: {exit_code}]\n"
                "```"
            )
            await container.mount(
                AssistantTextPart(
                    content=rendered,
                    part_id=f"shell-{hash(command)}",
                    classes="message assistant-message",
                )
            )

            if exit_code != 0:
                self.app.notify(
                    f"Shell command exited with code {exit_code}.",
                    severity="warning",
                )
            container.scroll_end()
        except Exception as exc:
            self.app.notify(f"Shell command failed: {exc}", severity="error")
            await self._remove_spinner()
        finally:
            prompt = self.query_one("#prompt-input", PromptInput)
            prompt.disabled = False
            prompt.focus()

    async def _remove_spinner(self) -> None:
        if not self._loading_spinner:
            return
        try:
            await self._loading_spinner.remove()
        except Exception:
            pass
        self._loading_spinner = None

    async def _begin_turn(self, container: ScrollableContainer, agent: str) -> None:
        await self._remove_spinner()
        await container.mount(
            MessageBubble(
                content="",
                role="assistant",
                agent=agent,
                classes="message assistant-message",
            )
        )
        self._uses_tool_part_updates = False
        self._legacy_tool_parts = {}
        self._active_turn = AssistantTurnState()

    async def _send_message_async(
        self, content: str, container: ScrollableContainer
    ) -> None:
        """Send a message and stream assistant output."""
        from ..core.bus import Bus
        from ..permission import Permission, PermissionAsked, PermissionReply
        from ..question import Question, QuestionAsked

        async def on_permission_asked(payload: Any) -> None:
            request_data = payload.properties
            prompt = self.query_one("#prompt-input", PromptInput)
            prompt.disabled = True
            try:
                result = await self.app.push_screen_wait(PermissionDialog(request=request_data))
                reply_type, message = result or ("reject", None)
                await Permission.reply(
                    request_id=request_data["id"],
                    reply=PermissionReply(reply_type),
                    message=message,
                )
            except Exception:
                await Permission.reply(
                    request_id=request_data["id"],
                    reply=PermissionReply.REJECT,
                )
            finally:
                prompt.disabled = False

        async def on_question_asked(payload: Any) -> None:
            request_data = payload.properties
            prompt = self.query_one("#prompt-input", PromptInput)
            prompt.disabled = True
            try:
                answers: List[List[str]] = []
                for question in request_data.get("questions", []):
                    title = question.get("header", "Question")
                    text = question.get("question", "Please choose")
                    options = question.get("options", []) or []
                    multiple = bool(question.get("multiple"))
                    allow_custom = question.get("custom", True)

                    if not options:
                        value = await self.app.push_screen_wait(
                            InputDialog(title=title, placeholder=text, submit_label="Submit")
                        )
                        answers.append([value] if value else [])
                        continue

                    if multiple:
                        lines = [f"{idx + 1}. {opt.get('label', f'Option {idx + 1}')}" for idx, opt in enumerate(options)]
                        prompt_text = f"{text}\n\n" + "\n".join(lines) + "\n\nEnter comma-separated option numbers."
                        raw = await self.app.push_screen_wait(
                            InputDialog(title=title, placeholder=prompt_text, submit_label="Submit")
                        )
                        selected: List[str] = []
                        if isinstance(raw, str):
                            for item in [piece.strip() for piece in raw.split(",") if piece.strip()]:
                                if item.isdigit():
                                    idx = int(item)
                                    if 1 <= idx <= len(options):
                                        selected.append(options[idx - 1].get("label", f"Option {idx}"))
                        if allow_custom and not selected:
                            custom = await self.app.push_screen_wait(
                                InputDialog(title=title, placeholder="Custom answer", submit_label="Submit")
                            )
                            if custom:
                                selected.append(custom)
                        answers.append(selected)
                        continue

                    dialog_options = [
                        (f"{opt.get('label', f'Option {idx + 1}')}: {opt.get('description', '')}", opt.get("label", ""))
                        for idx, opt in enumerate(options)
                    ]
                    selected = await self.app.push_screen_wait(
                        SelectDialog(title=f"{title}: {text}", options=dialog_options)
                    )
                    if selected is None and allow_custom:
                        custom = await self.app.push_screen_wait(
                            InputDialog(title=title, placeholder="Custom answer", submit_label="Submit")
                        )
                        answers.append([custom] if custom else [])
                    elif selected is None:
                        answers.append([])
                    else:
                        answers.append([selected])

                await Question.reply(request_data["id"], answers)
            except Exception:
                await Question.reject(request_data["id"])
            finally:
                prompt.disabled = False

        unsub = Bus.subscribe(PermissionAsked, on_permission_asked)
        unsub_question = Bus.subscribe(QuestionAsked, on_question_asked)
        try:
            sdk = use_sdk()
            sync = use_sync()
            local = use_local()

            agent = local.agent.current().get("name", "build")
            model_selection = local.model.current()
            model = None
            if model_selection:
                model = f"{model_selection.provider_id}/{model_selection.model_id}"

            if not self.session_id:
                session_data = await sdk.create_session(agent=agent, model=model)
                self.session_id = session_data["id"]
                sync.update_session(session_data)
                route = use_route()
                if route.is_session():
                    route.data.session_id = self.session_id
                self._refresh_header()

            enriched_content, attached_paths, warnings = enrich_content_with_file_references(
                content,
                cwd=sdk.cwd,
            )
            for warning in warnings:
                self.app.notify(warning, severity="warning")
            if attached_paths:
                attached_text = ", ".join(attached_paths[:3])
                if len(attached_paths) > 3:
                    attached_text += ", ..."
                self.app.notify(
                    f"Attached {len(attached_paths)} file(s): {attached_text}",
                    severity="information",
                )

            async for event in sdk.send_message(
                session_id=self.session_id,
                content=enriched_content,
                agent=agent,
                model=model,
                files=[{"path": path} for path in attached_paths] if attached_paths else None,
            ):
                event_type = event.get("type")
                if event_type == "message.created":
                    await self._begin_turn(container, agent)
                elif event_type == "message.part.updated":
                    await self._handle_part_update(event, container, agent)
                elif event_type == "message.part.tool.start":
                    await self._handle_tool_start(event, container, agent)
                elif event_type == "message.part.tool.end":
                    await self._handle_tool_end(event, container)
                elif event_type == "message.completed":
                    self._active_turn = None
                    if self.session_id:
                        await sync.sync_session(self.session_id, force=True)
                        session_data = sync.get_session(self.session_id)
                        if session_data and isinstance(session_data.get("agent"), str):
                            local.agent.set(session_data["agent"])
                            self._refresh_prompt_meta()
                elif event_type == "error":
                    error_msg = event.get("data", {}).get("error", "Unknown error")
                    self.app.notify(f"Error: {error_msg}", severity="error")
                    await self._remove_spinner()

                container.scroll_end()
        except Exception as e:
            self.app.notify(f"Error sending message: {str(e)}", severity="error")
            await self._remove_spinner()
        finally:
            unsub()
            unsub_question()
            await self._remove_spinner()
            self._active_turn = None
            prompt = self.query_one("#prompt-input", PromptInput)
            prompt.disabled = False
            prompt.focus()

    async def _ensure_turn(
        self, container: ScrollableContainer, agent: str
    ) -> AssistantTurnState:
        if self._active_turn is None:
            await self._begin_turn(container, agent)
        return self._active_turn or AssistantTurnState()

    async def _handle_part_update(
        self, event: Dict[str, Any], container: ScrollableContainer, agent: str
    ) -> None:
        part = event.get("data", {}).get("part", {})
        part_type = part.get("type")
        if part_type == "text":
            part_id = part.get("id", "")
            text = part.get("text", "")
            turn = await self._ensure_turn(container, agent)

            widget = turn.text_parts.get(part_id)
            if widget:
                widget.content = text
                widget.refresh()
                return

            text_widget = AssistantTextPart(
                content=text,
                part_id=part_id,
                classes="message assistant-message",
            )
            turn.text_parts[part_id] = text_widget
            await container.mount(text_widget)
            return
        if part_type == "tool":
            self._uses_tool_part_updates = True
            await self._handle_tool_part_update(part, container, agent)
            return

    async def _handle_tool_part_update(
        self,
        part: Dict[str, Any],
        container: ScrollableContainer,
        agent: str,
    ) -> None:
        tool_key = self._tool_widget_key(part)
        if not tool_key:
            return
        turn = await self._ensure_turn(container, agent)
        widget = turn.tool_widgets.get(tool_key)
        if widget:
            widget.show_details = self._show_tool_details
            widget.set_part(part)
            widget.refresh()
            return
        if self._should_hide_tool_part(part):
            return
        widget = ToolDisplay(
            part=part,
            show_details=self._show_tool_details,
            on_open_session=self._open_task_session,
            classes="message tool-display",
        )
        turn.tool_widgets[tool_key] = widget
        await container.mount(widget)

    @staticmethod
    def _tool_widget_key(part: Dict[str, Any]) -> str:
        call_id = part.get("call_id")
        if isinstance(call_id, str) and call_id:
            return call_id
        part_id = part.get("id")
        if isinstance(part_id, str) and part_id:
            return part_id
        return ""

    def _should_hide_tool_part(self, part: Dict[str, Any]) -> bool:
        if self._show_tool_details:
            return False
        state = part.get("state")
        if not isinstance(state, dict):
            return False
        status = state.get("status")
        error = state.get("error")
        return status == "completed" and not error

    def _open_task_session(self, session_id: str) -> None:
        route = use_route()
        route.navigate(SessionRoute(session_id=session_id))

    async def _handle_tool_start(
        self, event: Dict[str, Any], container: ScrollableContainer, agent: str
    ) -> None:
        if self._uses_tool_part_updates:
            return
        data = event.get("data", {})
        tool_id = data.get("tool_id", "")
        tool_name = data.get("tool_name", "tool")
        input_data = data.get("input", {})
        now_ms = int(time.time() * 1000)
        part_id = self._legacy_tool_parts.get(tool_id, {}).get("id")
        part = {
            "id": part_id or f"tool-{tool_id or tool_name}",
            "type": "tool",
            "tool": tool_name,
            "call_id": tool_id,
            "state": {
                "status": "running",
                "input": input_data if isinstance(input_data, dict) else {},
                "raw": "",
                "output": None,
                "error": None,
                "title": "",
                "metadata": {},
                "attachments": [],
                "time": {"start": now_ms, "end": None},
            },
        }
        self._legacy_tool_parts[tool_id] = part
        await self._handle_tool_part_update(part, container, agent)

    async def _handle_tool_end(
        self, event: Dict[str, Any], container: ScrollableContainer
    ) -> None:
        if self._uses_tool_part_updates or self._active_turn is None:
            return

        data = event.get("data", {})
        tool_id = data.get("tool_id", "")
        existing = self._legacy_tool_parts.get(tool_id)
        if not existing:
            return
        state = dict(existing.get("state") or {})
        state["status"] = "error" if data.get("error") else "completed"
        state["output"] = data.get("output")
        state["error"] = data.get("error")
        state["title"] = data.get("title", "")
        metadata = data.get("metadata", {})
        state["metadata"] = metadata if isinstance(metadata, dict) else {}
        time_info = dict(state.get("time") or {})
        time_info["end"] = int(time.time() * 1000)
        state["time"] = time_info
        existing["state"] = state
        self._legacy_tool_parts[tool_id] = existing
        await self._handle_tool_part_update(
            existing,
            container,
            use_local().agent.current().get("name", "assistant"),
        )

    def action_command_palette(self) -> None:
        self.app.action_command_palette()

    def action_new_session(self) -> None:
        use_route().navigate(HomeRoute())

    def action_session_list(self) -> None:
        self.app.action_session_list()

    def action_go_home(self) -> None:
        use_route().navigate(HomeRoute())

    def action_page_up(self) -> None:
        self.query_one("#messages-container", ScrollableContainer).scroll_page_up()

    def action_page_down(self) -> None:
        self.query_one("#messages-container", ScrollableContainer).scroll_page_down()

    def action_cycle_agent(self) -> None:
        local = use_local()
        local.agent.move(1)
        self._refresh_prompt_meta()

    def action_undo(self) -> None:
        self.app.execute_command("session.undo", source="keybind")

    def action_redo(self) -> None:
        self.app.execute_command("session.redo", source="keybind")

    def submit_message(self, content: str) -> None:
        """Submit a prompt programmatically."""
        self._send_message(content)

    async def refresh_history(self) -> None:
        """Refresh session messages from persisted storage."""
        await self._load_session_history()

    def set_tool_details_visibility(self, visible: bool) -> None:
        """Update tool detail visibility and refresh timeline rendering."""
        self._show_tool_details = bool(visible)
        if self._active_turn:
            for widget in self._active_turn.tool_widgets.values():
                widget.show_details = self._show_tool_details
                widget.refresh()
        prompt = self.query_one("#prompt-input", PromptInput)
        if prompt.disabled:
            return
        self.run_worker(self._load_session_history(), exclusive=False)

    def set_prompt_text(self, text: str) -> None:
        """Set prompt input value and keep focus on input."""
        prompt = self.query_one("#prompt-input", PromptInput)
        prompt.value = text
        prompt.cursor_position = len(text)
        prompt.focus()

    def action_quit(self) -> None:
        self.app.exit()
