"""Screens for TUI application."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, ScrollableContainer
from textual.screen import Screen
from textual.widgets import Static

from .commands import CommandRegistry, create_default_commands
from .context import use_local, use_route, use_sdk, use_sync
from .context.route import HomeRoute, PromptInfo, SessionRoute
from .dialogs import PermissionDialog
from .widgets import (
    AssistantTextPart,
    Logo,
    MessageBubble,
    PromptInput,
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
        Binding("ctrl+x", "command_palette", "Commands"),
        Binding("ctrl+s", "session_list", "Sessions"),
        Binding("ctrl+d", "quit", "Quit"),
    ]

    CSS = """
    HomeScreen {
        align: center middle;
    }

    #home-container {
        width: 80;
        height: auto;
        align: center middle;
    }

    #logo-container {
        width: 100%;
        height: auto;
        align: center middle;
        padding: 2;
    }

    #prompt-container {
        width: 100%;
        height: auto;
        padding: 1 2;
    }

    #status-container {
        width: 100%;
        height: 1;
        padding: 0 2;
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
        slash_commands = _build_slash_commands(self._command_registry)
        yield Container(
            Container(Logo(), id="logo-container"),
            Container(
                PromptInput(
                    placeholder="What would you like to do?",
                    commands=slash_commands,
                    id="prompt-input",
                ),
                id="prompt-container",
            ),
            Container(StatusBar(id="status-bar"), id="status-container"),
            id="home-container",
        )

    def on_mount(self) -> None:
        prompt = self.query_one("#prompt-input", PromptInput)
        prompt.focus()
        if self.initial_prompt:
            prompt.value = self.initial_prompt

    def on_prompt_input_submitted(self, event: PromptInput.Submitted) -> None:
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

    def action_quit(self) -> None:
        self.app.exit()


class SessionScreen(Screen):
    """Session screen with message history and prompt input."""

    BINDINGS = [
        Binding("ctrl+x", "command_palette", "Commands"),
        Binding("ctrl+n", "new_session", "New"),
        Binding("ctrl+s", "session_list", "Sessions"),
        Binding("escape", "go_home", "Home"),
        Binding("pageup", "page_up", "Page Up", show=False),
        Binding("pagedown", "page_down", "Page Down", show=False),
        Binding("ctrl+d", "quit", "Quit"),
    ]

    CSS = """
    SessionScreen {
        layout: vertical;
    }

    #session-header {
        height: 3;
        padding: 0 2;
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
        self._command_registry = CommandRegistry()
        for cmd in create_default_commands():
            self._command_registry.register(cmd)

    def compose(self) -> ComposeResult:
        slash_commands = _build_slash_commands(self._command_registry)
        yield Container(
            Static("Session", id="session-title"),
            StatusBar(id="session-status"),
            id="session-header",
        )
        yield ScrollableContainer(id="messages-container")
        yield Container(
            PromptInput(
                placeholder="Type your message...",
                commands=slash_commands,
                id="prompt-input",
            ),
            id="prompt-container",
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

        agent = use_local().agent.current().get("name", "assistant")
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
            elif part_type == "tool-invocation":
                invocation = part.get("tool_invocation", {})
                if not isinstance(invocation, dict):
                    continue

                state = invocation.get("state")
                tool_name = invocation.get("tool_name", "tool")
                tool_id = invocation.get("tool_call_id", f"history-tool-{idx}")
                args = invocation.get("args") or {}

                if state == "result":
                    output = invocation.get("result")
                    await container.mount(
                        ToolDisplay(
                            tool_name=tool_name,
                            tool_id=tool_id,
                            status="completed",
                            input_data=args if isinstance(args, dict) else {},
                            output=self._stringify_output(output),
                            classes="message tool-display",
                        )
                    )
                elif state in ("call", "partial-call"):
                    await container.mount(
                        ToolDisplay(
                            tool_name=tool_name,
                            tool_id=tool_id,
                            status="running",
                            input_data=args if isinstance(args, dict) else {},
                            classes="message tool-display",
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
        """Refresh session title and status line."""
        title = self.query_one("#session-title", Static)
        if self.session_id:
            title.update(f"Session {self.session_id[:8]}")
        else:
            title.update("Session")

        local = use_local()
        status = self.query_one("#session-status", StatusBar)
        model_selection = local.model.current()
        status.model = (
            f"{model_selection.provider_id}/{model_selection.model_id}"
            if model_selection
            else None
        )
        status.agent = local.agent.current().get("name", "build")
        status.session_id = self.session_id
        status.refresh()

    def on_prompt_input_submitted(self, event: PromptInput.Submitted) -> None:
        self._send_message(event.value)

    def on_prompt_input_slash_command_selected(
        self, event: PromptInput.SlashCommandSelected
    ) -> None:
        self.app.execute_command(event.command_id, source="slash")

    def _send_message(self, content: str) -> None:
        content = content.strip()
        if not content:
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
        self._active_turn = AssistantTurnState()

    async def _send_message_async(
        self, content: str, container: ScrollableContainer
    ) -> None:
        """Send a message and stream assistant output."""
        from ..core.bus import Bus
        from ..permission import Permission, PermissionAsked, PermissionReply

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

        unsub = Bus.subscribe(PermissionAsked, on_permission_asked)
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

            async for event in sdk.send_message(
                session_id=self.session_id,
                content=content,
                agent=agent,
                model=model,
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
        if part.get("type") != "text":
            return

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

    async def _handle_tool_start(
        self, event: Dict[str, Any], container: ScrollableContainer, agent: str
    ) -> None:
        data = event.get("data", {})
        tool_id = data.get("tool_id", "")
        tool_name = data.get("tool_name", "tool")
        input_data = data.get("input", {})
        turn = await self._ensure_turn(container, agent)

        widget = turn.tool_widgets.get(tool_id)
        if widget:
            widget.status = "running"
            widget.input_data = input_data
            widget.refresh()
            return

        widget = ToolDisplay(
            tool_name=tool_name,
            tool_id=tool_id,
            status="running",
            input_data=input_data,
            classes="message tool-display",
        )
        turn.tool_widgets[tool_id] = widget
        await container.mount(widget)

    async def _handle_tool_end(
        self, event: Dict[str, Any], container: ScrollableContainer
    ) -> None:
        if self._active_turn is None:
            return

        data = event.get("data", {})
        tool_id = data.get("tool_id", "")
        widget = self._active_turn.tool_widgets.get(tool_id)
        if not widget:
            return

        widget.output = data.get("output")
        widget.error = data.get("error")
        widget.title = data.get("title", "")
        widget.metadata = data.get("metadata", {})
        widget.status = "error" if data.get("error") else "completed"
        widget.refresh()

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

    def action_quit(self) -> None:
        self.app.exit()
