"""Screens for TUI application."""

import asyncio
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, ScrollableContainer
from textual.screen import Screen
from textual.widgets import Static

from .commands import CommandRegistry, create_default_commands
from .context import SyncEvent, use_kv, use_local, use_route, use_sdk, use_sync
from .context.route import HomeRoute, PromptInfo, SessionRoute
from .dialogs import InputDialog, PermissionDialog, SelectDialog
from .header_usage import compute_session_header_usage
from .input_parsing import enrich_content_with_file_references
from .state import ScreenSubscriptions, select_runtime_status
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

_INTERRUPT_WINDOW_SECONDS = 5.0


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
        self._subscriptions = ScreenSubscriptions()
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
        yield AppFooter(
            directory=sdk.cwd,
            version=__version__,
            id="home-footer",
        )

    def on_mount(self) -> None:
        prompt = self.query_one("#prompt-input", PromptInput)
        prompt.focus()
        if self.initial_prompt:
            prompt.value = self.initial_prompt
        self._refresh_prompt_meta()
        self._refresh_footer()
        self._bind_subscriptions()

    def on_unmount(self) -> None:
        self._subscriptions.clear()

    def _bind_subscriptions(self) -> None:
        sync = use_sync()
        local = use_local()

        self._subscriptions.add(sync.on(SyncEvent.MCP_UPDATED, lambda _data: self._refresh_footer()))
        self._subscriptions.add(sync.on(SyncEvent.LSP_UPDATED, lambda _data: self._refresh_footer()))
        self._subscriptions.add(local.agent.on_change(lambda _name: self._refresh_prompt_meta()))
        self._subscriptions.add(local.model.on_change(lambda _model: self._refresh_prompt_meta()))

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

    def _refresh_footer(self) -> None:
        snapshot = select_runtime_status(sync=use_sync(), route=use_route())
        footer = self.query_one("#home-footer", AppFooter)
        footer.apply_runtime_snapshot(snapshot, show_lsp=False)

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
        Binding("escape", "session_escape", "Esc"),
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
        self._subscriptions = ScreenSubscriptions()
        self._loading_spinner: Optional[Spinner] = None
        self._history_refresh_scheduled = False
        self._history_refresh_running = False
        self._show_tool_details = bool(use_kv().get("tool_details_visibility", True))
        self._show_thinking = bool(use_kv().get("thinking_visibility", True))
        self._show_assistant_metadata = bool(use_kv().get("assistant_metadata_visibility", True))
        self._show_timestamps = str(use_kv().get("timestamps", "hide")) == "show"
        self._interrupt_until = 0.0
        self._interrupt_pending = False
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
        yield AppFooter(
            directory=sdk.cwd,
            show_lsp=True,
            version=__version__,
            id="session-footer",
        )

    def on_mount(self) -> None:
        prompt = self.query_one("#prompt-input", PromptInput)
        prompt.focus()
        self._bind_subscriptions()
        self._refresh_header()
        self._refresh_footer()

        if self.session_id:
            self.run_worker(self._load_session_history(), exclusive=False)

        if self.initial_message:
            self.call_after_refresh(lambda: self._send_message(self.initial_message or ""))

    def on_unmount(self) -> None:
        self._subscriptions.clear()

    def _bind_subscriptions(self) -> None:
        sync = use_sync()
        local = use_local()

        self._subscriptions.add(sync.on(SyncEvent.MCP_UPDATED, lambda _data: self._refresh_footer()))
        self._subscriptions.add(sync.on(SyncEvent.LSP_UPDATED, lambda _data: self._refresh_footer()))
        self._subscriptions.add(sync.on(SyncEvent.PERMISSION_UPDATED, lambda _data: self._refresh_footer()))
        self._subscriptions.add(sync.on(SyncEvent.SESSION_STATUS_UPDATED, lambda _data: self._refresh_header()))
        self._subscriptions.add(sync.on(SyncEvent.MESSAGES_UPDATED, self._on_messages_updated))
        self._subscriptions.add(local.agent.on_change(lambda _name: self._refresh_prompt_meta()))
        self._subscriptions.add(local.model.on_change(lambda _model: self._refresh_prompt_meta()))

    def _on_messages_updated(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        if payload.get("session_id") != self.session_id:
            return
        self._refresh_header()
        self._schedule_history_refresh()

    def _schedule_history_refresh(self) -> None:
        if self._history_refresh_scheduled:
            return
        self._history_refresh_scheduled = True
        self.run_worker(self._refresh_history_debounced(), exclusive=False)

    async def _refresh_history_debounced(self) -> None:
        await asyncio.sleep(0.016)
        self._history_refresh_scheduled = False
        if self._history_refresh_running:
            self._schedule_history_refresh()
            return
        self._history_refresh_running = True
        try:
            await self._load_session_history(sync_if_needed=False)
            container = self.query_one("#messages-container", ScrollableContainer)
            container.scroll_end()
        finally:
            self._history_refresh_running = False

    async def _load_session_history(self, sync_if_needed: bool = True) -> None:
        """Load and render historical messages for an existing session."""
        if not self.session_id:
            return
        self._show_tool_details = bool(use_kv().get("tool_details_visibility", True))
        self._show_thinking = bool(use_kv().get("thinking_visibility", True))
        self._show_assistant_metadata = bool(use_kv().get("assistant_metadata_visibility", True))
        self._show_timestamps = str(use_kv().get("timestamps", "hide")) == "show"

        sync = use_sync()
        sdk = use_sdk()
        if sync_if_needed and not sync.is_session_synced(self.session_id):
            await sync.sync_session(self.session_id, sdk)

        container = self.query_one("#messages-container", ScrollableContainer)
        container.remove_children()
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
        timestamp = self._message_timestamp(message.get("info"))
        if role == "user":
            text = self._extract_text(message)
            await container.mount(
                MessageBubble(
                    content=text,
                    role="user",
                    timestamp=timestamp,
                    classes="message user-message",
                )
            )
            await self._mount_structured_parts(
                message=message,
                container=container,
                prefix=f"history-{message.get('id', '')}",
                include_text=False,
            )
            return

        info = message.get("info", {})
        agent = self._assistant_label_from_info(info)
        await container.mount(
            MessageBubble(
                content="",
                role="assistant",
                agent=agent,
                timestamp=timestamp,
                classes="message assistant-message",
            )
        )

        await self._mount_structured_parts(
            message=message,
            container=container,
            prefix=f"history-{message.get('id', '')}",
            include_text=True,
        )

    async def _mount_structured_parts(
        self,
        *,
        message: Dict[str, Any],
        container: ScrollableContainer,
        prefix: str,
        include_text: bool,
    ) -> None:
        parts = message.get("parts", [])
        for idx, part in enumerate(parts):
            if not isinstance(part, dict):
                continue

            part_type = part.get("type")
            if not include_text and part_type in {"text", "reasoning"}:
                continue
            if part_type == "tool":
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
                continue

            content = self._render_part_content(part)
            if not content:
                continue
            part_id = str(part.get("id") or f"{prefix}-{idx}")
            await container.mount(
                AssistantTextPart(
                    content=content,
                    part_id=part_id,
                    classes="message assistant-message",
                )
            )

    def _render_part_content(self, part: Dict[str, Any]) -> str:
        part_type = str(part.get("type") or "")
        if part_type == "text":
            return str(part.get("text") or "")
        if part_type == "reasoning":
            if not self._show_thinking:
                return ""
            text = str(part.get("text") or "").strip()
            if not text:
                return ""
            return f"_Thinking:_\n\n{text}"
        if part_type == "step-start":
            return "_Step started._"
        if part_type == "step-finish":
            reason = str(part.get("reason") or "completed")
            lines = [f"_Step finished: {reason}._"]
            if self._show_tool_details:
                tokens = part.get("tokens")
                if isinstance(tokens, dict):
                    token_line = (
                        f"input={int(tokens.get('input', 0) or 0)}, "
                        f"output={int(tokens.get('output', 0) or 0)}, "
                        f"reasoning={int(tokens.get('reasoning', 0) or 0)}"
                    )
                    lines.extend(["", f"`{token_line}`"])
            return "\n".join(lines)
        if part_type == "patch":
            files = part.get("files")
            file_list = files if isinstance(files, list) else []
            lines = [f"_Patch changed {len(file_list)} file(s)._"]
            if self._show_tool_details and file_list:
                lines.append("")
                lines.extend(f"- `{str(item)}`" for item in file_list)
            return "\n".join(lines)
        if part_type == "compaction":
            mode = "auto" if bool(part.get("auto")) else "manual"
            return f"_Compaction checkpoint ({mode})._"
        if part_type == "subtask":
            description = str(part.get("description") or "subtask")
            agent = str(part.get("agent") or "subagent")
            return f"**Subtask ({agent}):** {description}"
        if part_type == "file":
            filename = str(part.get("filename") or "attachment")
            url = str(part.get("url") or "")
            if url:
                return f"**File:** {filename} ({url})"
            return f"**File:** {filename}"
        return ""

    def _assistant_label_from_info(self, info: Any) -> Optional[str]:
        if not self._show_assistant_metadata:
            return None
        agent = use_local().agent.current().get("name", "assistant")
        if not isinstance(info, dict):
            return agent
        info_agent = info.get("agent")
        if isinstance(info_agent, str) and info_agent:
            agent = info_agent
        model = info.get("model")
        if isinstance(model, dict):
            provider_id = str(model.get("provider_id") or "")
            model_id = str(model.get("model_id") or "")
            if provider_id and model_id:
                return f"{agent} · {provider_id}/{model_id}"
            if model_id:
                return f"{agent} · {model_id}"
        return agent

    def _message_timestamp(self, info: Any) -> Optional[str]:
        if not self._show_timestamps or not isinstance(info, dict):
            return None
        time_data = info.get("time")
        if not isinstance(time_data, dict):
            return None
        created = time_data.get("created")
        if not isinstance(created, (int, float)):
            return None
        try:
            return datetime.fromtimestamp(created / 1000).astimezone().strftime("%H:%M:%S")
        except (ValueError, OSError):
            return None

    def _now_timestamp(self) -> Optional[str]:
        if not self._show_timestamps:
            return None
        return datetime.now().astimezone().strftime("%H:%M:%S")

    def _extract_text(self, message: Dict[str, Any]) -> str:
        parts = message.get("parts", [])
        chunks: List[str] = []
        files: List[str] = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            part_type = part.get("type")
            if part_type == "text":
                text = part.get("text")
                if isinstance(text, str):
                    chunks.append(text)
            if part_type == "file":
                files.append(str(part.get("filename") or "attachment"))
        base = "".join(chunks)
        if not files:
            return base
        attached = ", ".join(files[:3])
        if len(files) > 3:
            attached = f"{attached}, ..."
        suffix = f"[Attached: {attached}]"
        return f"{base}\n\n{suffix}" if base else suffix

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
            usage = compute_session_header_usage(
                messages=messages,
                providers=sync.data.providers,
            )
            header.context_info = usage.context_info
            header.cost = usage.cost
        else:
            header.context_info = ""
            header.cost = ""

        header.refresh()
        if not self._is_busy():
            self._reset_interrupt()
        self._refresh_prompt_meta()
        self._refresh_footer()

    def _reset_interrupt(self) -> None:
        self._interrupt_until = 0.0
        self._interrupt_pending = False

    def _interrupt_armed(self, now: float) -> bool:
        if self._interrupt_until <= 0:
            return False
        if now <= self._interrupt_until:
            return True
        self._interrupt_until = 0.0
        return False

    def _session_status(self) -> str:
        if not self.session_id:
            return "idle"
        status = use_sync().data.session_status.get(self.session_id)
        if not isinstance(status, dict):
            return "idle"
        value = status.get("type")
        if not isinstance(value, str) or not value:
            return "idle"
        return value

    def _is_busy(self) -> bool:
        if self._session_status() != "idle":
            return True
        if not self.is_mounted:
            return False
        prompt = self.query_one("#prompt-input", PromptInput)
        return bool(prompt.disabled)

    def _escape_mode(self, now: float) -> str:
        if not self.session_id or not self._is_busy():
            return "home"
        if self._interrupt_pending:
            return "pending"
        if self._interrupt_armed(now):
            self._interrupt_until = 0.0
            self._interrupt_pending = True
            return "interrupt"
        self._interrupt_until = now + _INTERRUPT_WINDOW_SECONDS
        return "armed"

    async def _interrupt_session(self) -> None:
        if not self.session_id:
            self._reset_interrupt()
            return

        try:
            result = await use_sdk().interrupt(self.session_id)
        except Exception as exc:
            self._interrupt_pending = False
            self.app.notify(f"Interrupt failed: {exc}", severity="error")
            return

        if not bool(result.get("interrupted")):
            self._interrupt_pending = False
            self.app.notify("No active response to interrupt.", severity="warning")
            return
        self.app.notify("Interrupt requested.", severity="information")

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

    def _refresh_footer(self) -> None:
        snapshot = select_runtime_status(sync=use_sync(), route=use_route())
        footer = self.query_one("#session-footer", AppFooter)
        footer.apply_runtime_snapshot(snapshot, show_lsp=True)

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
        self._reset_interrupt()

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
        self._loading_spinner = Spinner("Thinking...")
        container.mount(self._loading_spinner)

        prompt = self.query_one("#prompt-input", PromptInput)
        prompt.disabled = True

        self.run_worker(
            self._send_message_async(content),
            exclusive=True,
        )

    def _send_shell_command(self, raw_input: str, command: str) -> None:
        """Execute a local shell command in session view."""
        container = self.query_one("#messages-container", ScrollableContainer)
        container.mount(
            MessageBubble(
                content=raw_input,
                role="user",
                timestamp=self._now_timestamp(),
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
                    timestamp=self._now_timestamp(),
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

    async def _send_message_async(self, content: str) -> None:
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

            finalized = False
            async for event in sdk.send_message(
                session_id=self.session_id,
                content=enriched_content,
                agent=agent,
                model=model,
                files=[{"path": path} for path in attached_paths] if attached_paths else None,
            ):
                event_type = event.get("type")
                if event_type == "session.status":
                    status_data = event.get("data", {}).get("status", {})
                    status_type = status_data.get("type") if isinstance(status_data, dict) else None
                    if status_type != "idle":
                        continue
                    finalized = True
                    if self.session_id:
                        session_data = sync.get_session(self.session_id)
                        if session_data and isinstance(session_data.get("agent"), str):
                            local.agent.set(session_data["agent"])
                            self._refresh_prompt_meta()
                elif event_type == "error":
                    error_msg = event.get("data", {}).get("error", "Unknown error")
                    self.app.notify(f"Error: {error_msg}", severity="error")
                    await self._remove_spinner()

            # OpenCode-like behavior: message request completion is authoritative.
            # If idle event was missed in transit, force a final sync after stream loop exits.
            if self.session_id and not finalized:
                await sync.sync_session(self.session_id, sdk, force=True)
                session_data = sync.get_session(self.session_id)
                if session_data and isinstance(session_data.get("agent"), str):
                    local.agent.set(session_data["agent"])
                    self._refresh_prompt_meta()
                await self._load_session_history()
            container = self.query_one("#messages-container", ScrollableContainer)
            container.scroll_end()
        except Exception as e:
            self.app.notify(f"Error sending message: {str(e)}", severity="error")
            await self._remove_spinner()
        finally:
            unsub()
            unsub_question()
            await self._remove_spinner()
            prompt = self.query_one("#prompt-input", PromptInput)
            prompt.disabled = False
            prompt.focus()
            self._reset_interrupt()

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

    def action_command_palette(self) -> None:
        self.app.action_command_palette()

    def action_new_session(self) -> None:
        use_route().navigate(HomeRoute())

    def action_session_list(self) -> None:
        self.app.action_session_list()

    def action_go_home(self) -> None:
        use_route().navigate(HomeRoute())

    def action_session_escape(self) -> None:
        mode = self._escape_mode(time.monotonic())
        if mode == "home":
            self.action_go_home()
            return
        if mode == "pending":
            self.app.notify("Interrupt request in progress...", severity="information")
            return
        if mode == "armed":
            self.app.notify(
                f"Press Esc again within {int(_INTERRUPT_WINDOW_SECONDS)}s to interrupt.",
                severity="warning",
            )
            return
        self.app.notify("Interrupting...", severity="information")
        self.run_worker(self._interrupt_session(), exclusive=False)

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
        prompt = self.query_one("#prompt-input", PromptInput)
        if prompt.disabled:
            return
        self.run_worker(self._load_session_history(), exclusive=False)

    def set_thinking_visibility(self, visible: bool) -> None:
        """Update thinking visibility and refresh timeline rendering."""
        self._show_thinking = bool(visible)
        prompt = self.query_one("#prompt-input", PromptInput)
        if prompt.disabled:
            return
        self.run_worker(self._load_session_history(), exclusive=False)

    def set_assistant_metadata_visibility(self, visible: bool) -> None:
        """Update assistant metadata visibility and refresh timeline rendering."""
        self._show_assistant_metadata = bool(visible)
        prompt = self.query_one("#prompt-input", PromptInput)
        if prompt.disabled:
            return
        self.run_worker(self._load_session_history(), exclusive=False)

    def set_timestamps_visibility(self, visible: bool) -> None:
        """Update timestamp visibility and refresh timeline rendering."""
        self._show_timestamps = bool(visible)
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
