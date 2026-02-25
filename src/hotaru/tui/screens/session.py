"""Session screen with message history and prompt input."""

import asyncio
import time
from typing import Any, Dict, List, Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, ScrollableContainer
from textual.screen import Screen

from ..commands import CommandRegistry, create_default_commands
from ..context import SyncEvent, use_kv, use_local, use_route, use_sdk, use_sync
from ..context.route import HomeRoute, SessionRoute
from ..header_usage import compute_session_header_usage
from ..state import ScreenSubscriptions, select_runtime_status
from ..widgets import (
    AppFooter,
    AssistantTextPart,
    MessageBubble,
    PromptHints,
    PromptInput,
    PromptMeta,
    SessionHeaderBar,
    Spinner,
    ToolDisplay,
)
from ._helpers import _INTERRUPT_WINDOW_SECONDS, build_slash_commands
from ._rendering import (
    assistant_label,
    extract_text,
    message_timestamp,
    render_part,
    should_hide_tool,
)
from ._messaging import MessagingMixin


class SessionScreen(MessagingMixin, Screen):
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
        from ... import __version__

        slash_commands = build_slash_commands(self._command_registry)

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
        timestamp = message_timestamp(message.get("info"), show=self._show_timestamps)
        if role == "user":
            text = extract_text(message)
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
        agent = assistant_label(info, show_metadata=self._show_assistant_metadata)
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
                if should_hide_tool(part, show_details=self._show_tool_details):
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

            content = render_part(
                part,
                show_thinking=self._show_thinking,
                show_tool_details=self._show_tool_details,
            )
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
