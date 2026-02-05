"""Main TUI application.

This module provides the main Textual application class for the
Hotaru Code terminal user interface.
"""

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer
from textual.screen import Screen
from textual.command import CommandPalette, Provider, Hit, Hits
from typing import Optional, List
import asyncio

from .screens import HomeScreen, SessionScreen
from .theme import ThemeManager, Theme
from .commands import CommandRegistry, Command, create_default_commands
from .event import TuiEvent
from .context import (
    RouteProvider, RouteContext, HomeRoute, SessionRoute,
    ArgsProvider, Args,
    KVProvider,
    LocalProvider,
    SyncProvider,
)
from ..core.bus import Bus
from ..util.log import Log

log = Log.create({"service": "tui.app"})


class HotaruCommandProvider(Provider):
    """Command provider for the command palette.

    Provides searchable commands for the Textual command palette.
    """

    @property
    def commands(self) -> List[Command]:
        """Get available commands."""
        app = self.app
        if isinstance(app, TuiApp):
            return app.command_registry.list_commands()
        return []

    async def search(self, query: str) -> Hits:
        """Search for commands matching query.

        Args:
            query: Search query

        Yields:
            Matching command hits
        """
        query = query.lower()

        for command in self.commands:
            if not command.enabled:
                continue

            # Check if query matches title
            if query in command.title.lower():
                yield Hit(
                    command.title,
                    command.on_select or (lambda: None),
                    help=f"[{command.category.value}]",
                )
                continue

            # Check slash command
            if command.slash_name and query in command.slash_name.lower():
                yield Hit(
                    command.title,
                    command.on_select or (lambda: None),
                    help=f"/{command.slash_name}",
                )


class TuiApp(App):
    """Main TUI application for Hotaru Code.

    Provides a rich terminal interface for interacting with the
    AI coding assistant.
    """

    TITLE = "Hotaru Code"
    SUB_TITLE = "AI-powered coding assistant"

    CSS = """
    Screen {
        background: $background;
    }

    .hidden {
        display: none;
    }

    Toast {
        layer: notification;
    }
    """

    BINDINGS = [
        Binding("ctrl+x", "command_palette", "Commands", show=True),
        Binding("ctrl+n", "new_session", "New", show=False),
        Binding("ctrl+s", "session_list", "Sessions", show=False),
        Binding("ctrl+m", "model_list", "Models", show=False),
        Binding("ctrl+t", "toggle_theme", "Theme", show=False),
        Binding("ctrl+q", "quit", "Quit", show=True),
    ]

    COMMANDS = {HotaruCommandProvider}

    def __init__(
        self,
        session_id: Optional[str] = None,
        initial_prompt: Optional[str] = None,
        model: Optional[str] = None,
        agent: Optional[str] = None,
        continue_session: bool = False,
        **kwargs
    ) -> None:
        """Initialize the TUI application.

        Args:
            session_id: Session ID to continue
            initial_prompt: Initial prompt to send
            model: Model to use (provider/model format)
            agent: Agent to use
            continue_session: Whether to continue last session
        """
        super().__init__(**kwargs)

        self.session_id = session_id
        self.initial_prompt = initial_prompt
        self.model = model
        self.agent = agent
        self.continue_session = continue_session

        # Initialize contexts
        self._init_contexts()

        # Initialize command registry
        self.command_registry = CommandRegistry()
        self._register_default_commands()

        # Load theme preference
        ThemeManager.load_preference()

        # Apply theme
        self._apply_theme()

        log.info("TUI app initialized", {
            "session_id": session_id,
            "model": model,
            "agent": agent,
            "continue_session": continue_session,
        })

    def _init_contexts(self) -> None:
        """Initialize all context providers."""
        # Args context
        self.args_ctx = ArgsProvider.provide(Args(
            model=self.model,
            agent=self.agent,
            session_id=self.session_id,
            continue_session=self.continue_session,
            prompt=self.initial_prompt,
        ))

        # KV context for preferences
        self.kv_ctx = KVProvider.provide()

        # Route context
        self.route_ctx = RouteProvider.provide()

        # SDK context for API communication
        from .context import SDKProvider
        self.sdk_ctx = SDKProvider.provide()

        # Sync context for data
        self.sync_ctx = SyncProvider.provide()

        # Local context for agent/model selection
        self.local_ctx = LocalProvider.provide()

        # Listen for route changes
        self.route_ctx.on_change(self._on_route_change)

    def _on_route_change(self, route) -> None:
        """Handle route changes.

        Args:
            route: New route
        """
        log.debug("route changed", {"type": route.type})

        if route.type == "home":
            # Navigate to home screen
            self.switch_screen(HomeScreen(
                initial_prompt=route.initial_prompt.input if route.initial_prompt else None
            ))
        elif route.type == "session":
            # Navigate to session screen
            self.switch_screen(SessionScreen(
                session_id=route.session_id,
                initial_message=route.initial_prompt.input if route.initial_prompt else None
            ))

    def _register_default_commands(self) -> None:
        """Register default commands."""
        for command in create_default_commands():
            # Bind command callbacks
            if command.id == "app.exit":
                command.on_select = self.exit
            elif command.id == "theme.toggle_mode":
                command.on_select = self.action_toggle_theme
            elif command.id == "session.new":
                command.on_select = self.action_new_session
            elif command.id == "session.list":
                command.on_select = self.action_session_list
            elif command.id == "model.list":
                command.on_select = self.action_model_list
            elif command.id == "help.show":
                command.on_select = self._show_help

            self.command_registry.register(command)

    def _apply_theme(self) -> None:
        """Apply the current theme to the app."""
        theme = ThemeManager.get_theme()

        # Update CSS variables
        self.dark = ThemeManager.get_mode() == "dark"

    def _show_help(self) -> None:
        """Show help dialog."""
        from .dialogs import HelpDialog
        self.push_screen(HelpDialog())

    def compose(self) -> ComposeResult:
        """Compose the application."""
        yield Footer()

    def on_mount(self) -> None:
        """Handle application mount."""
        # Determine initial screen
        if self.session_id:
            # Continue specific session
            self.push_screen(SessionScreen(session_id=self.session_id))
        elif self.continue_session:
            # Continue last session - try to find most recent
            self._continue_last_session()
        elif self.initial_prompt:
            # Start with initial prompt
            self.push_screen(HomeScreen(initial_prompt=self.initial_prompt))
        else:
            # Show home screen
            self.push_screen(HomeScreen())

    def _continue_last_session(self) -> None:
        """Try to continue the last session."""
        # Get sessions from sync context
        sessions = self.sync_ctx.data.sessions
        if sessions:
            # Find most recent non-child session
            for session in sorted(sessions, key=lambda s: s.get("time", {}).get("updated", 0), reverse=True):
                if not session.get("parentID"):
                    self.push_screen(SessionScreen(session_id=session["id"]))
                    return

        # No sessions found, show home
        self.push_screen(HomeScreen())

    def action_toggle_theme(self) -> None:
        """Toggle between dark and light theme."""
        new_mode = ThemeManager.toggle_mode()
        self._apply_theme()
        self.notify(f"Switched to {new_mode} mode")

    def action_command_palette(self) -> None:
        """Show the command palette."""
        self.push_screen(CommandPalette())

    def action_new_session(self) -> None:
        """Start a new session."""
        self.route_ctx.navigate(HomeRoute())

    def action_session_list(self) -> None:
        """Show session list dialog."""
        from .dialogs import SessionListDialog
        sessions = self.sync_ctx.data.sessions
        current_id = self.route_ctx.get_session_id()

        session_data = [
            {
                "id": s.get("id", ""),
                "title": s.get("title", "Untitled"),
                "updated": s.get("time", {}).get("updated", ""),
            }
            for s in sessions
            if not s.get("parentID")  # Only show parent sessions
        ]

        self.push_screen(
            SessionListDialog(
                sessions=session_data,
                current_session_id=current_id
            ),
            callback=self._on_session_selected
        )

    def _on_session_selected(self, result) -> None:
        """Handle session selection from dialog."""
        if result is None:
            return

        action, session_id = result
        if action == "select" and session_id:
            self.route_ctx.navigate(SessionRoute(session_id=session_id))
        elif action == "new":
            self.route_ctx.navigate(HomeRoute())

    def action_model_list(self) -> None:
        """Show model selection dialog."""
        from .dialogs import ModelSelectDialog

        # Build providers dict from sync data
        providers = {}
        for provider in self.sync_ctx.data.providers:
            provider_id = provider.get("id", "")
            models = provider.get("models", {})
            providers[provider_id] = [
                {"id": model_id, "name": model_info.get("name", model_id)}
                for model_id, model_info in models.items()
            ]

        current = self.local_ctx.model.current()
        current_model = None
        if current:
            current_model = (current.provider_id, current.model_id)

        self.push_screen(
            ModelSelectDialog(
                providers=providers,
                current_model=current_model
            ),
            callback=self._on_model_selected
        )

    def _on_model_selected(self, result) -> None:
        """Handle model selection from dialog."""
        if result is None:
            return

        provider_id, model_id = result
        from .context.local import ModelSelection
        self.local_ctx.model.set(
            ModelSelection(provider_id=provider_id, model_id=model_id),
            add_to_recent=True
        )
        self.notify(f"Switched to {provider_id}/{model_id}")

    def action_quit(self) -> None:
        """Quit the application."""
        self.exit()

    async def show_toast(
        self,
        message: str,
        variant: str = "info",
        title: Optional[str] = None,
        duration: float = 5.0
    ) -> None:
        """Show a toast notification.

        Args:
            message: Toast message
            variant: Style variant (info, success, warning, error)
            title: Optional title
            duration: Display duration in seconds
        """
        # Use Textual's built-in notify
        severity = "information"
        if variant == "error":
            severity = "error"
        elif variant == "warning":
            severity = "warning"

        self.notify(
            message,
            title=title,
            severity=severity,
            timeout=duration
        )


def run_tui(
    session_id: Optional[str] = None,
    initial_prompt: Optional[str] = None,
    model: Optional[str] = None,
    agent: Optional[str] = None,
    continue_session: bool = False,
) -> None:
    """Run the TUI application.

    Args:
        session_id: Session ID to continue
        initial_prompt: Initial prompt to send
        model: Model to use
        agent: Agent to use
        continue_session: Whether to continue last session
    """
    app = TuiApp(
        session_id=session_id,
        initial_prompt=initial_prompt,
        model=model,
        agent=agent,
        continue_session=continue_session,
    )
    app.run()
