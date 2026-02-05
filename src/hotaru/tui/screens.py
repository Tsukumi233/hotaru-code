"""Screens for TUI application.

This module provides the main screens used in the TUI,
including the home screen and session screen.
"""

from textual.app import ComposeResult
from textual.screen import Screen
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import Static, Input, Button, Footer, Header
from textual.binding import Binding
from rich.text import Text
from rich.panel import Panel
from rich.markdown import Markdown
from typing import Optional, List
import asyncio

from .widgets import (
    Logo, PromptInput, MessageBubble, ToolDisplay,
    StatusBar, Spinner, Toast, SlashCommandItem
)
from .theme import ThemeManager
from .context import use_sdk, use_sync, use_local
from .commands import CommandRegistry, create_default_commands


def _build_slash_commands(registry: CommandRegistry) -> List[SlashCommandItem]:
    """Build slash command items from registry.

    Args:
        registry: Command registry

    Returns:
        List of slash command items
    """
    items = []
    for cmd in registry.list_commands():
        if cmd.slash_name:
            items.append(SlashCommandItem(
                id=cmd.id,
                trigger=cmd.slash_name,
                title=cmd.title,
                description="",
                keybind=cmd.keybind,
                type="builtin",
            ))
            # Add aliases as separate items
            for alias in cmd.slash_aliases:
                items.append(SlashCommandItem(
                    id=cmd.id,
                    trigger=alias,
                    title=cmd.title,
                    description=f"Alias for /{cmd.slash_name}",
                    keybind=cmd.keybind,
                    type="builtin",
                ))
    return items


class HomeScreen(Screen):
    """Home screen with logo and prompt.

    The initial screen shown when starting the TUI,
    featuring the Hotaru logo and a prompt input.
    """

    BINDINGS = [
        Binding("ctrl+x", "command_palette", "Commands"),
        Binding("ctrl+s", "session_list", "Sessions"),
        Binding("ctrl+q", "quit", "Quit"),
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

    def __init__(
        self,
        initial_prompt: Optional[str] = None,
        **kwargs
    ) -> None:
        """Initialize home screen.

        Args:
            initial_prompt: Optional initial prompt text
        """
        super().__init__(**kwargs)
        self.initial_prompt = initial_prompt
        self._command_registry = CommandRegistry()
        for cmd in create_default_commands():
            self._command_registry.register(cmd)

    def compose(self) -> ComposeResult:
        """Compose the home screen."""
        # Build slash commands from registry
        slash_commands = _build_slash_commands(self._command_registry)

        yield Container(
            Container(Logo(), id="logo-container"),
            Container(
                PromptInput(
                    placeholder="What would you like to do?",
                    commands=slash_commands,
                    id="prompt-input"
                ),
                id="prompt-container"
            ),
            Container(
                StatusBar(id="status-bar"),
                id="status-container"
            ),
            id="home-container"
        )

    def on_mount(self) -> None:
        """Handle mount event."""
        # Focus the prompt input
        prompt = self.query_one("#prompt-input", PromptInput)
        prompt.focus()

        # Set initial prompt if provided
        if self.initial_prompt:
            prompt.value = self.initial_prompt

    def on_prompt_input_submitted(self, event: PromptInput.Submitted) -> None:
        """Handle prompt submission."""
        # Create new session and navigate to it
        self.app.push_screen(SessionScreen(initial_message=event.value))

    def on_prompt_input_slash_command_selected(self, event: PromptInput.SlashCommandSelected) -> None:
        """Handle slash command selection."""
        self._execute_slash_command(event.command_id)

    def _execute_slash_command(self, command_id: str) -> None:
        """Execute a slash command.

        Args:
            command_id: Command ID to execute
        """
        # Map command IDs to actions
        if command_id == "session.new":
            self.app.push_screen(HomeScreen())
        elif command_id == "session.list":
            self.app.action_session_list()
        elif command_id == "model.list":
            self.app.action_model_list()
        elif command_id == "theme.toggle_mode":
            self.app.action_toggle_theme()
        elif command_id == "help.show":
            self.app.notify("Help: Type a message or use /commands")
        elif command_id == "app.exit":
            self.app.exit()

    def action_command_palette(self) -> None:
        """Show command palette."""
        self.app.action_command_palette()

    def action_session_list(self) -> None:
        """Show session list."""
        # TODO: Implement session list dialog
        pass

    def action_quit(self) -> None:
        """Quit the application."""
        self.app.exit()


class SessionScreen(Screen):
    """Session screen with message history and prompt.

    Displays the conversation history and allows sending new messages.
    """

    BINDINGS = [
        Binding("ctrl+x", "command_palette", "Commands"),
        Binding("ctrl+n", "new_session", "New"),
        Binding("ctrl+s", "session_list", "Sessions"),
        Binding("escape", "go_home", "Home"),
        Binding("pageup", "page_up", "Page Up", show=False),
        Binding("pagedown", "page_down", "Page Down", show=False),
        Binding("ctrl+q", "quit", "Quit"),
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
        **kwargs
    ) -> None:
        """Initialize session screen.

        Args:
            session_id: Session ID to load
            initial_message: Initial message to send
        """
        super().__init__(**kwargs)
        self.session_id = session_id
        self.initial_message = initial_message
        self._messages: list = []
        self._command_registry = CommandRegistry()
        for cmd in create_default_commands():
            self._command_registry.register(cmd)

    def compose(self) -> ComposeResult:
        """Compose the session screen."""
        # Build slash commands from registry
        slash_commands = _build_slash_commands(self._command_registry)

        yield Container(
            Static("Session", id="session-title"),
            StatusBar(id="session-status"),
            id="session-header"
        )
        yield ScrollableContainer(id="messages-container")
        yield Container(
            PromptInput(
                placeholder="Type your message...",
                commands=slash_commands,
                id="prompt-input"
            ),
            id="prompt-container"
        )

    def on_mount(self) -> None:
        """Handle mount event."""
        # Focus the prompt input
        prompt = self.query_one("#prompt-input", PromptInput)
        prompt.focus()

        # Send initial message if provided
        if self.initial_message:
            self._send_message(self.initial_message)

    def on_prompt_input_submitted(self, event: PromptInput.Submitted) -> None:
        """Handle prompt submission."""
        self._send_message(event.value)

    def on_prompt_input_slash_command_selected(self, event: PromptInput.SlashCommandSelected) -> None:
        """Handle slash command selection."""
        self._execute_slash_command(event.command_id)

    def _execute_slash_command(self, command_id: str) -> None:
        """Execute a slash command.

        Args:
            command_id: Command ID to execute
        """
        # Map command IDs to actions
        if command_id == "session.new":
            self.app.push_screen(HomeScreen())
        elif command_id == "session.list":
            self.app.action_session_list()
        elif command_id == "model.list":
            self.app.action_model_list()
        elif command_id == "theme.toggle_mode":
            self.app.action_toggle_theme()
        elif command_id == "help.show":
            self.app.notify("Help: Type a message or use /commands")
        elif command_id == "app.exit":
            self.app.exit()
        elif command_id == "session.compact":
            self.app.notify("Compact: Session compaction not yet implemented")
        elif command_id == "session.export":
            self.app.notify("Export: Session export not yet implemented")
        elif command_id == "session.copy":
            self.app.notify("Copy: Session copy not yet implemented")

    def _send_message(self, content: str) -> None:
        """Send a message and get AI response.

        Args:
            content: Message content
        """
        # Add user message to display
        messages_container = self.query_one("#messages-container")
        user_bubble = MessageBubble(
            content=content,
            role="user",
            classes="message user-message"
        )
        messages_container.mount(user_bubble)

        # Scroll to bottom
        messages_container.scroll_end()

        # Add loading indicator
        spinner = Spinner("Thinking...", id="loading-spinner")
        messages_container.mount(spinner)

        # Start async message sending using run_worker
        self.run_worker(self._send_message_async(content, messages_container), exclusive=True)

    async def _send_message_async(self, content: str, container: ScrollableContainer) -> None:
        """Send message asynchronously and stream response.

        Args:
            content: Message content
            container: Container to add messages to
        """
        try:
            # Get contexts
            sdk = use_sdk()
            sync = use_sync()
            local = use_local()

            # Get current agent and model
            agent = local.agent.current().get("name", "build")
            model_selection = local.model.current()
            model = None
            if model_selection:
                model = f"{model_selection.provider_id}/{model_selection.model_id}"

            # Create session if needed
            if not self.session_id:
                session_data = await sdk.create_session(agent=agent, model=model)
                self.session_id = session_data["id"]
                sync.update_session(session_data)

            # Stream the response
            current_text = ""
            assistant_bubble = None

            async for event in sdk.send_message(
                session_id=self.session_id,
                content=content,
                agent=agent,
                model=model,
            ):
                event_type = event.get("type")

                if event_type == "message.created":
                    # Remove spinner
                    try:
                        spinner = self.query_one("#loading-spinner")
                        await spinner.remove()
                    except Exception:
                        pass

                    # Create assistant message bubble
                    assistant_bubble = MessageBubble(
                        content="",
                        role="assistant",
                        agent=agent,
                        classes="message assistant-message"
                    )
                    await container.mount(assistant_bubble)

                elif event_type == "message.part.updated":
                    # Update text content
                    part = event.get("data", {}).get("part", {})
                    if part.get("type") == "text":
                        current_text = part.get("text", "")
                        if assistant_bubble:
                            # Update the bubble content
                            assistant_bubble.content = current_text
                            assistant_bubble.refresh()

                elif event_type == "message.completed":
                    # Message complete
                    pass

                # Scroll to bottom
                container.scroll_end()

        except Exception as e:
            # Show error
            self.app.notify(f"Error sending message: {str(e)}", severity="error")

            # Remove spinner if still there
            try:
                spinner = self.query_one("#loading-spinner")
                await spinner.remove()
            except Exception:
                pass

    def action_command_palette(self) -> None:
        """Show command palette."""
        self.app.action_command_palette()

    def action_new_session(self) -> None:
        """Start a new session."""
        self.app.push_screen(HomeScreen())

    def action_session_list(self) -> None:
        """Show session list."""
        # TODO: Implement session list dialog
        pass

    def action_go_home(self) -> None:
        """Go back to home screen."""
        self.app.pop_screen()

    def action_page_up(self) -> None:
        """Scroll messages up."""
        container = self.query_one("#messages-container")
        container.scroll_page_up()

    def action_page_down(self) -> None:
        """Scroll messages down."""
        container = self.query_one("#messages-container")
        container.scroll_page_down()

    def action_quit(self) -> None:
        """Quit the application."""
        self.app.exit()
