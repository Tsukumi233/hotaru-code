"""Main TUI application.

This module provides the main Textual application class for the
Hotaru Code terminal user interface.
"""

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer
from textual.command import CommandPalette, Provider, Hit, Hits
from pathlib import Path
import re
from urllib.parse import urlparse
from typing import List, Optional
from pydantic import ValidationError

from .screens import HomeScreen, SessionScreen
from .theme import ThemeManager
from .commands import CommandRegistry, Command, create_default_commands
from .transcript import TranscriptOptions, format_transcript
from .context import (
    RouteProvider, HomeRoute, SessionRoute,
    ArgsProvider, Args,
    KVProvider,
    LocalProvider,
    SyncProvider,
)
from .context.route import PromptInfo
from ..util.log import Log

log = Log.create({"service": "tui.app"})

_PROVIDER_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]*\Z")


def _validate_provider_id(value: str) -> str:
    provider_id = value.strip().lower()
    if not provider_id:
        raise ValueError("Provider ID cannot be empty.")
    if not _PROVIDER_ID_PATTERN.fullmatch(provider_id):
        raise ValueError("Provider ID must match [a-z0-9][a-z0-9_-]*.")
    return provider_id


def _validate_base_url(value: str) -> str:
    base_url = value.strip()
    if not base_url:
        raise ValueError("Base URL cannot be empty.")

    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Base URL must be a valid http(s) URL.")
    return base_url


def _parse_model_ids(value: str) -> List[str]:
    model_ids: List[str] = []
    seen = set()

    for item in value.split(","):
        model_id = item.strip()
        if not model_id:
            continue
        if any(char.isspace() for char in model_id):
            raise ValueError(f"Model ID '{model_id}' cannot contain whitespace.")
        if model_id in seen:
            continue
        seen.add(model_id)
        model_ids.append(model_id)

    if not model_ids:
        raise ValueError("Please provide at least one model ID.")
    return model_ids


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

        app = self.app
        if not isinstance(app, TuiApp):
            return

        for command in self.commands:
            # Check if query matches title
            if query in command.title.lower():
                help_text = f"[{command.category.value}]"
                if not command.enabled and command.availability_reason:
                    help_text = f"{help_text} {command.availability_reason}"
                yield Hit(
                    command.title,
                    lambda cid=command.id: app.execute_command(cid, source="palette"),
                    help=help_text,
                )
                continue

            # Check slash command
            if command.slash_name and query in command.slash_name.lower():
                help_text = f"/{command.slash_name}"
                if not command.enabled and command.availability_reason:
                    help_text = f"{help_text} ({command.availability_reason})"
                yield Hit(
                    command.title,
                    lambda cid=command.id: app.execute_command(cid, source="palette"),
                    help=help_text,
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
        Binding("ctrl+a", "agent_list", "Agents", show=False),
        Binding("ctrl+t", "toggle_theme", "Theme", show=False),
        Binding("ctrl+d", "quit", "Quit", show=True),
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

        target = None
        if route.type == "home":
            target = HomeScreen(
                initial_prompt=route.initial_prompt.input if route.initial_prompt else None
            )
        elif route.type == "session":
            target = SessionScreen(
                session_id=route.session_id,
                initial_message=route.initial_prompt.input if route.initial_prompt else None
            )

        if target is None:
            return

        try:
            self.screen
        except Exception:
            self.push_screen(target)
            return

        self.switch_screen(target)

    def _register_default_commands(self) -> None:
        """Register default commands."""
        for command in create_default_commands():
            # Bind command callbacks
            if command.id == "app.exit":
                command.on_select = lambda source="palette": self.exit()
            elif command.id in ("theme.toggle_mode", "theme.switch"):
                command.on_select = lambda source="palette": self.action_toggle_theme()
            elif command.id == "session.new":
                command.on_select = lambda source="palette": self.action_new_session()
            elif command.id == "session.list":
                command.on_select = lambda source="palette": self.action_session_list()
            elif command.id == "session.share":
                command.on_select = lambda source="palette": self.action_session_share()
            elif command.id == "session.export":
                command.on_select = lambda source="palette": self.action_session_export()
            elif command.id == "session.copy":
                command.on_select = lambda source="palette": self.action_session_copy()
            elif command.id == "provider.connect":
                command.on_select = lambda source="palette": self.action_provider_connect()
            elif command.id == "model.list":
                command.on_select = lambda source="palette": self.action_model_list()
            elif command.id == "agent.list":
                command.on_select = lambda source="palette": self.action_agent_list()
            elif command.id in ("mcp.list", "status.view"):
                command.on_select = lambda source="palette": self.action_status_view()
            elif command.id == "help.show":
                command.on_select = lambda source="palette": self._show_help()

            self.command_registry.register(command)

    def _apply_theme(self) -> None:
        """Apply the current theme to the app."""
        self.dark = ThemeManager.get_mode() == "dark"

    def _show_help(self) -> None:
        """Show help dialog."""
        from .dialogs import HelpDialog
        self.push_screen(HelpDialog())

    def compose(self) -> ComposeResult:
        """Compose the application."""
        yield Footer()

    async def on_mount(self) -> None:
        """Handle application mount — runs async bootstrap then shows screen."""
        await self._bootstrap()

        # Determine initial screen
        if self.session_id:
            initial_route = SessionRoute(session_id=self.session_id)
        elif self.continue_session:
            initial_route = self._continue_last_session()
        elif self.initial_prompt:
            initial_route = HomeRoute(
                initial_prompt=PromptInfo(input=self.initial_prompt)
            )
        else:
            initial_route = HomeRoute()

        # Set initial route without notifying route listeners.
        self.route_ctx._route = initial_route
        self.push_screen(self._build_screen_for_route(initial_route))

    async def _bootstrap(self) -> None:
        """Load persisted data into contexts before showing the first screen."""
        try:
            from ..project import Project
            from ..session import Session
            from ..provider import Provider as ProviderModule
            from ..agent import Agent
            from .context.local import ModelSelection

            # Ensure project context
            project, _ = await Project.from_directory(self.sdk_ctx.cwd)

            # Load sessions into SyncContext
            sessions = await Session.list(project.id)
            session_dicts = [
                {
                    "id": s.id,
                    "title": s.title or "Untitled",
                    "agent": s.agent,
                    "parentID": s.parent_id,
                    "share": s.share.model_dump() if s.share else None,
                    "time": {
                        "created": s.time.created,
                        "updated": s.time.updated,
                    },
                }
                for s in sessions
            ]
            self.sync_ctx.set_sessions(session_dicts)

            provider_dicts = await self._sync_providers()

            # Load agents into SyncContext
            agents = await Agent.list()
            agent_dicts = [
                {
                    "name": a.name,
                    "mode": a.mode,
                    "hidden": a.hidden,
                    "description": a.description or "",
                }
                for a in agents
            ]
            self.sync_ctx.set_agents(agent_dicts)
            self.local_ctx.update_agents(agent_dicts)

            # Initialize model and agent selection
            try:
                model_value = self.model
                if model_value:
                    provider_id, model_id = ProviderModule.parse_model(model_value)
                else:
                    provider_id, model_id = await ProviderModule.default_model()
                self.local_ctx.model.set(
                    ModelSelection(provider_id=provider_id, model_id=model_id),
                    add_to_recent=True
                )
            except Exception as e:
                log.warning("failed to set initial model", {"error": str(e)})

            try:
                agent_name = self.agent or await Agent.default_agent()
                self.local_ctx.agent.set(agent_name)
            except Exception as e:
                log.warning("failed to set initial agent", {"error": str(e)})

            await self._refresh_runtime_status()

            self.sync_ctx.set_status("complete")
            log.info("bootstrap complete", {
                "sessions": len(session_dicts),
                "providers": len(provider_dicts),
                "agents": len(agent_dicts),
            })
        except Exception as e:
            log.error("bootstrap error", {"error": str(e)})
            self.sync_ctx.set_status("partial")

    async def _sync_providers(self) -> List[dict]:
        """Load providers and publish them to sync/local contexts."""
        from ..provider import Provider as ProviderModule

        providers = await ProviderModule.list()
        provider_dicts = [
            {
                "id": pid,
                "name": provider.name,
                "models": {
                    model_id: {
                        "id": model_id,
                        "name": model.name,
                        "api_id": model.api_id,
                    }
                    for model_id, model in provider.models.items()
                },
            }
            for pid, provider in providers.items()
        ]
        self.sync_ctx.set_providers(provider_dicts)
        self.local_ctx.update_providers(provider_dicts)
        return provider_dicts

    async def _refresh_runtime_status(self) -> None:
        """Refresh MCP and LSP runtime status in sync context."""
        try:
            from ..mcp import MCP

            mcp_status = await MCP.status()
            self.sync_ctx.set_mcp_status({
                name: status.model_dump()
                for name, status in mcp_status.items()
            })
        except Exception as e:
            log.warning("failed to load MCP status", {"error": str(e)})
            self.sync_ctx.set_mcp_status({})

        try:
            from ..lsp import LSP

            lsp_status = await LSP.status()
            self.sync_ctx.set_lsp_status([item.model_dump() for item in lsp_status])
        except Exception as e:
            log.warning("failed to load LSP status", {"error": str(e)})
            self.sync_ctx.set_lsp_status([])

    def _build_screen_for_route(self, route):
        """Build a screen instance for a route."""
        if route.type == "session":
            return SessionScreen(
                session_id=route.session_id,
                initial_message=route.initial_prompt.input if route.initial_prompt else None
            )
        return HomeScreen(
            initial_prompt=route.initial_prompt.input if route.initial_prompt else None
        )

    def _continue_last_session(self):
        """Resolve the route for continuing the last session."""
        sessions = self.sync_ctx.data.sessions
        if sessions:
            # Find most recent non-child session
            for session in sorted(
                sessions,
                key=lambda s: s.get("time", {}).get("updated", 0),
                reverse=True,
            ):
                if not session.get("parentID"):
                    return SessionRoute(session_id=session["id"])

        # No sessions found, show home
        return HomeRoute()

    def execute_command(self, command_id: str, source: str = "palette") -> None:
        """Execute a command and surface unavailable reasons to the user."""
        executed, reason = self.command_registry.execute(command_id, source=source)
        if executed:
            return

        if reason:
            self.notify(reason, severity="warning")
            return
        self.notify("Command is not available right now.", severity="warning")

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

    def action_model_list(self, provider_filter: Optional[str] = None) -> None:
        """Show model selection dialog."""
        from .dialogs import ModelSelectDialog

        # Build providers dict from sync data
        providers = {}
        for provider in self.sync_ctx.data.providers:
            provider_id = provider.get("id", "")
            if provider_filter and provider_id != provider_filter:
                continue
            models = provider.get("models", {})
            providers[provider_id] = [
                {"id": model_id, "name": model_info.get("name", model_id)}
                for model_id, model_info in models.items()
            ]

        if not providers:
            self.notify("No models available for selection.", severity="warning")
            return

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

    def action_provider_connect(self) -> None:
        """Start interactive provider onboarding."""
        self.run_worker(self._provider_connect_flow(), exclusive=False)

    async def _provider_connect_flow(self) -> None:
        from ..core.config import ConfigManager, ProviderConfig
        from ..provider import Provider as ProviderModule
        from ..provider.auth import ProviderAuth
        from .dialogs import InputDialog, SelectDialog

        provider_type = await self.push_screen_wait(
            SelectDialog(
                title="Provider protocol",
                options=[
                    ("OpenAI-compatible API", "openai"),
                    ("Anthropic-compatible API", "anthropic"),
                ],
            )
        )
        if provider_type is None:
            return

        provider_id = await self.push_screen_wait(
            InputDialog(
                title="Provider ID",
                placeholder="my-provider",
                submit_label="Next",
            )
        )
        if provider_id is None:
            return
        try:
            provider_id = _validate_provider_id(str(provider_id))
        except ValueError as exc:
            self.notify(str(exc), severity="error")
            return

        provider_name = await self.push_screen_wait(
            InputDialog(
                title="Provider display name",
                placeholder="Optional (defaults to provider ID)",
                default_value=provider_id,
                submit_label="Next",
            )
        )
        if provider_name is None:
            return
        provider_name = provider_name.strip() or provider_id

        base_url = await self.push_screen_wait(
            InputDialog(
                title="Base URL",
                placeholder="https://api.example.com/v1",
                submit_label="Next",
            )
        )
        if base_url is None:
            return
        try:
            base_url = _validate_base_url(str(base_url))
        except ValueError as exc:
            self.notify(str(exc), severity="error")
            return

        api_key = await self.push_screen_wait(
            InputDialog(
                title="API key",
                placeholder="sk-...",
                submit_label="Next",
                password=True,
            )
        )
        if api_key is None:
            return
        api_key = api_key.strip()
        if not api_key:
            self.notify("API key cannot be empty.", severity="error")
            return

        model_value = await self.push_screen_wait(
            InputDialog(
                title="Model IDs",
                placeholder="gpt-4o-mini, claude-sonnet-4-5",
                submit_label="Connect",
            )
        )
        if model_value is None:
            return

        try:
            model_ids = _parse_model_ids(str(model_value))
        except ValueError as exc:
            self.notify(str(exc), severity="error")
            return

        models = {model_id: {"name": model_id} for model_id in model_ids}
        provider_payload = {
            "type": provider_type,
            "name": provider_name,
            "options": {"baseURL": base_url},
            "models": models,
        }
        try:
            ProviderConfig.model_validate(provider_payload)
        except ValidationError:
            self.notify("Generated provider config is invalid.", severity="error")
            return

        updates = {
            "provider": {
                provider_id: provider_payload
            }
        }

        try:
            await ConfigManager.update_global(updates)
            ProviderAuth.set(provider_id, api_key)
            ProviderModule.reset()
            await self._sync_providers()
        except Exception as exc:
            self.notify(f"Failed to connect provider: {exc}", severity="error")
            return

        self.notify(f"Connected provider '{provider_id}'.")
        self.action_model_list(provider_filter=provider_id)

    def action_agent_list(self) -> None:
        """Show agent selection dialog."""
        from .dialogs import AgentSelectDialog

        agents = [
            a for a in self.sync_ctx.data.agents
            if not a.get("hidden") and a.get("mode") != "subagent"
        ]
        current = self.local_ctx.agent.current().get("name", "build")

        self.push_screen(
            AgentSelectDialog(agents=agents, current_agent=current),
            callback=self._on_agent_selected
        )

    def _on_agent_selected(self, agent_name: Optional[str]) -> None:
        """Handle agent selection from dialog."""
        if not agent_name:
            return

        if self.local_ctx.agent.set(agent_name):
            self.notify(f"Switched to {agent_name}")
            return
        self.notify(f"Agent '{agent_name}' is unavailable", severity="warning")

    def action_status_view(self) -> None:
        """Show runtime status dialog."""
        self.run_worker(self._show_status_dialog(), exclusive=False)

    async def _show_status_dialog(self) -> None:
        """Refresh and show runtime status."""
        from .dialogs import StatusDialog

        await self._refresh_runtime_status()

        current_model = self.local_ctx.model.current()
        model = "(auto)"
        if current_model:
            model = f"{current_model.provider_id}/{current_model.model_id}"
        agent = self.local_ctx.agent.current().get("name", "build")

        result = await self.push_screen_wait(
            StatusDialog(
                model=model,
                agent=agent,
                mcp=self.sync_ctx.data.mcp,
                lsp=self.sync_ctx.data.lsp,
            )
        )
        if result == "refresh":
            self.action_status_view()

    def action_session_copy(self) -> None:
        """Copy the current session transcript to clipboard."""
        self.run_worker(self._copy_session_transcript(), exclusive=False)

    async def _copy_session_transcript(self) -> None:
        session_id = self._active_session_id()
        if not session_id:
            self.notify("Open a session first to copy its transcript.", severity="warning")
            return

        transcript = await self._build_session_transcript(session_id)
        if transcript is None:
            return

        if self._copy_text_to_clipboard(transcript):
            self.notify("Session transcript copied to clipboard.")
            return

        self.notify("Failed to copy session transcript.", severity="error")

    def action_session_export(self) -> None:
        """Export the current session transcript to a markdown file."""
        self.run_worker(self._export_session_transcript(), exclusive=False)

    async def _export_session_transcript(self) -> None:
        from .dialogs import InputDialog

        session_id = self._active_session_id()
        if not session_id:
            self.notify("Open a session first to export its transcript.", severity="warning")
            return

        transcript = await self._build_session_transcript(session_id)
        if transcript is None:
            return

        default_name = f"session-{session_id[:8]}.md"
        result = await self.push_screen_wait(
            InputDialog(
                title="Export Session Transcript",
                placeholder="filename.md",
                default_value=default_name,
                submit_label="Export",
            )
        )
        if result is None:
            return

        filename = str(result).strip()
        if not filename:
            self.notify("Export canceled: filename is empty.", severity="warning")
            return
        if not filename.lower().endswith(".md"):
            filename = f"{filename}.md"

        output_path = Path(filename)
        if not output_path.is_absolute():
            output_path = Path(self.sdk_ctx.cwd) / output_path

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(transcript, encoding="utf-8")
        except Exception as exc:
            self.notify(f"Failed to export session transcript: {exc}", severity="error")
            return

        self.notify(f"Session exported to {output_path}")

    def action_session_share(self) -> None:
        """Share the current session by exporting a sharable markdown snapshot."""
        self.run_worker(self._share_session(), exclusive=False)

    async def _share_session(self) -> None:
        session_id = self._active_session_id()
        if not session_id:
            self.notify("Open a session first to share it.", severity="warning")
            return

        transcript = await self._build_session_transcript(session_id)
        if transcript is None:
            return

        share_dir = Path(self.sdk_ctx.cwd) / ".hotaru" / "share"
        share_path = share_dir / f"session-{session_id[:8]}.md"

        try:
            share_dir.mkdir(parents=True, exist_ok=True)
            share_path.write_text(transcript, encoding="utf-8")
        except Exception as exc:
            self.notify(f"Failed to share session: {exc}", severity="error")
            return

        share_uri = share_path.resolve().as_uri()
        if self._copy_text_to_clipboard(share_uri):
            self.notify("Share link copied to clipboard.")
            return
        self.notify(f"Session snapshot saved at {share_path}")

    def _active_session_id(self) -> Optional[str]:
        """Resolve the currently active session ID."""
        session_id = self.route_ctx.get_session_id()
        if session_id:
            return session_id

        try:
            screen = self.screen
        except Exception:
            return None

        if isinstance(screen, SessionScreen):
            return screen.session_id
        return None

    async def _build_session_transcript(self, session_id: str) -> Optional[str]:
        """Build transcript markdown for the given session."""
        sync = self.sync_ctx
        if not sync.is_session_synced(session_id):
            await sync.sync_session(session_id)

        session = sync.get_session(session_id)
        if not session:
            self.notify(f"Session '{session_id}' was not found.", severity="error")
            return None

        messages = sync.get_messages(session_id)
        if not messages:
            self.notify("Session has no messages yet.", severity="warning")
            return None

        options = TranscriptOptions(
            thinking=False,
            tool_details=True,
            assistant_metadata=True,
        )
        return format_transcript(session, messages, options)

    def _copy_text_to_clipboard(self, text: str) -> bool:
        """Copy text to clipboard with Textual's clipboard API."""
        try:
            self.copy_to_clipboard(text)
            return True
        except Exception:
            return False

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
