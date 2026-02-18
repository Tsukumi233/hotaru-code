"""Main TUI application.

This module provides the main Textual application class for the
Hotaru Code terminal user interface.
"""

import asyncio
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer
from textual.command import CommandPalette, Provider, Hit, Hits
from dataclasses import dataclass
from copy import deepcopy
from pathlib import Path
import re
from urllib.parse import urlparse
from typing import Any, Callable, Dict, List, Optional

from .routes import HomeScreen, SessionScreen
from .theme import ThemeManager
from .commands import CommandRegistry, Command, create_default_commands
from .transcript import TranscriptOptions, format_transcript
from .input_parsing import parse_slash_command
from .turns import extract_user_text_from_turn, split_messages_for_undo
from .context import (
    RouteProvider, HomeRoute, SessionRoute,
    ArgsProvider, Args,
    KVProvider,
    LocalProvider,
    SyncProvider,
)
from .state import select_runtime_status
from .context.route import PromptInfo
from ..util.log import Log
from ..command import render_init_prompt, publish_command_executed

log = Log.create({"service": "tui.app"})

_PROVIDER_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]*\Z")


@dataclass(frozen=True)
class _ProviderPreset:
    preset_id: str
    provider_type: str
    provider_id: str
    provider_name: str
    base_url: str
    default_models: str


_PROVIDER_PRESETS: Dict[str, _ProviderPreset] = {
    "moonshot": _ProviderPreset(
        preset_id="moonshot",
        provider_type="openai",
        provider_id="moonshot",
        provider_name="Moonshot",
        base_url="https://api.moonshot.cn/v1",
        default_models="kimi-k2.5",
    ),
}


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


def _resolve_provider_preset(preset_id: str) -> Optional[_ProviderPreset]:
    return _PROVIDER_PRESETS.get(str(preset_id or "").strip().lower())


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
        Binding("ctrl+p", "command_palette", "Commands", show=True),
        Binding("ctrl+n", "new_session", "New", show=False),
        Binding("ctrl+s", "session_list", "Sessions", show=False),
        Binding("ctrl+m", "model_list", "Models", show=False),
        Binding("ctrl+a", "agent_list", "Agents", show=False),
        Binding("ctrl+t", "toggle_theme", "Theme", show=False),
        Binding("ctrl+c", "quit", "Quit", show=True, priority=True),
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
        self._redo_turns: Dict[str, List[List[Dict[str, Any]]]] = {}
        self._runtime_unsubscribers: List[Callable[[], None]] = []
        self._lsp_refresh_task: Optional[asyncio.Task[None]] = None

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
                command.on_select = lambda source="palette", argument=None: self.exit()
            elif command.id in ("theme.toggle_mode", "theme.switch"):
                command.on_select = (
                    lambda source="palette", argument=None: self.action_toggle_theme()
                )
            elif command.id == "session.new":
                command.on_select = (
                    lambda source="palette", argument=None: self.action_new_session()
                )
            elif command.id == "project.init":
                command.on_select = (
                    lambda source="palette", argument=None: self.action_project_init(argument)
                )
            elif command.id == "session.list":
                command.on_select = (
                    lambda source="palette", argument=None: self.action_session_list()
                )
            elif command.id == "session.share":
                command.on_select = (
                    lambda source="palette", argument=None: self.action_session_share()
                )
            elif command.id == "session.undo":
                command.on_select = (
                    lambda source="palette", argument=None: self.action_session_undo()
                )
            elif command.id == "session.redo":
                command.on_select = (
                    lambda source="palette", argument=None: self.action_session_redo()
                )
            elif command.id == "session.rename":
                command.on_select = (
                    lambda source="palette", argument=None: self.action_session_rename(argument)
                )
            elif command.id == "session.compact":
                command.on_select = (
                    lambda source="palette", argument=None: self.action_session_compact()
                )
            elif command.id == "session.export":
                command.on_select = (
                    lambda source="palette", argument=None: self.action_session_export()
                )
            elif command.id == "session.copy":
                command.on_select = (
                    lambda source="palette", argument=None: self.action_session_copy()
                )
            elif command.id == "session.toggle.actions":
                command.on_select = (
                    lambda source="palette", argument=None: self.action_session_toggle_actions()
                )
            elif command.id == "session.toggle.thinking":
                command.on_select = (
                    lambda source="palette", argument=None: self.action_session_toggle_thinking()
                )
            elif command.id == "session.toggle.assistant_metadata":
                command.on_select = (
                    lambda source="palette", argument=None: self.action_session_toggle_assistant_metadata()
                )
            elif command.id == "session.toggle.timestamps":
                command.on_select = (
                    lambda source="palette", argument=None: self.action_session_toggle_timestamps()
                )
            elif command.id == "provider.connect":
                command.on_select = (
                    lambda source="palette", argument=None: self.action_provider_connect()
                )
            elif command.id == "model.list":
                command.on_select = (
                    lambda source="palette", argument=None: self.action_model_list(
                        provider_filter=argument or None
                    )
                )
            elif command.id == "agent.list":
                command.on_select = (
                    lambda source="palette", argument=None: self.action_agent_list()
                )
            elif command.id in ("mcp.list", "status.view"):
                command.on_select = (
                    lambda source="palette", argument=None: self.action_status_view()
                )
            elif command.id == "help.show":
                command.on_select = (
                    lambda source="palette", argument=None: self._show_help()
                )

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
        self._start_runtime_subscriptions()

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

    async def on_unmount(self) -> None:
        """Release runtime resources before the app exits."""
        await self._stop_runtime_subscriptions()
        await self.sdk_ctx.aclose()

        try:
            from ..mcp import MCP
            await MCP.shutdown()
        except Exception as e:
            log.warning("failed to shutdown MCP", {"error": str(e)})

        try:
            from ..lsp import LSP
            await LSP.shutdown()
        except Exception as e:
            log.warning("failed to shutdown LSP", {"error": str(e)})

    async def _bootstrap(self) -> None:
        """Load persisted data into contexts before showing the first screen."""
        try:
            from ..project import Project
            from .context.local import ModelSelection

            # Ensure project context
            project, _ = await Project.from_directory(self.sdk_ctx.cwd)

            # Load sessions into SyncContext
            sessions = await self.sdk_ctx.list_sessions(project_id=project.id)
            session_dicts = []
            for session in sessions:
                time_data = session.get("time", {}) if isinstance(session.get("time"), dict) else {}
                session_dicts.append(
                    {
                        "id": session.get("id"),
                        "title": session.get("title") or "Untitled",
                        "agent": session.get("agent"),
                        "parentID": session.get("parent_id"),
                        "share": session.get("share"),
                        "time": {
                            "created": int(time_data.get("created", 0) or 0),
                            "updated": int(time_data.get("updated", 0) or 0),
                        },
                    }
                )
            self.sync_ctx.set_sessions(session_dicts)

            provider_dicts = await self._sync_providers()

            # Load agents into SyncContext
            agent_dicts = await self.sdk_ctx.list_agents()
            self.sync_ctx.set_agents(agent_dicts)
            self.local_ctx.update_agents(agent_dicts)

            # Initialize model and agent selection
            try:
                selected_model: Optional[ModelSelection] = None

                if self.model:
                    provider_id, sep, model_id = self.model.partition("/")
                    if sep and provider_id.strip() and model_id.strip():
                        candidate = ModelSelection(provider_id=provider_id, model_id=model_id)
                        if self.local_ctx.model.is_available(candidate):
                            selected_model = candidate
                        else:
                            log.warning("requested startup model unavailable", {"model": self.model})
                    else:
                        log.warning("invalid startup model format", {"model": self.model})

                if selected_model is None:
                    selected_model = self.local_ctx.model.current()

                if selected_model is None:
                    selected_model = self.local_ctx.model.first_available()

                if selected_model is not None:
                    self.local_ctx.model.set(
                        selected_model,
                        add_to_recent=bool(self.model),
                    )
            except Exception as e:
                log.warning("failed to set initial model", {"error": str(e)})

            try:
                default_agent = self.agent
                if not default_agent and agent_dicts:
                    first_agent = agent_dicts[0]
                    if isinstance(first_agent, dict):
                        default_agent = str(first_agent.get("name") or "")
                if default_agent:
                    self.local_ctx.agent.set(default_agent)
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
        provider_dicts = await self.sdk_ctx.list_providers()
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

        await self._refresh_lsp_status()

    async def _refresh_lsp_status(self) -> None:
        """Refresh only LSP runtime status in sync context."""
        try:
            from ..lsp import LSP
            from ..project.instance import Instance

            lsp_status = await Instance.provide(
                directory=self.sdk_ctx.cwd,
                fn=LSP.status,
            )
            self.sync_ctx.set_lsp_status([item.model_dump() for item in lsp_status])
        except Exception as e:
            log.warning("failed to load LSP status", {"error": str(e)})
            self.sync_ctx.set_lsp_status([])

    def _start_runtime_subscriptions(self) -> None:
        """Subscribe to runtime events needed by the TUI."""
        if self._runtime_unsubscribers:
            return

        from ..core.bus import Bus, EventPayload
        from ..lsp.lsp import LSPUpdated
        from ..permission import PermissionAsked, PermissionReplied
        from ..question import QuestionAsked, QuestionRejected, QuestionReplied

        def on_lsp_updated(_event: EventPayload) -> None:
            self._schedule_lsp_refresh()

        def on_permission_asked(event: EventPayload) -> None:
            payload = event.properties
            session_id = str(payload.get("session_id") or "")
            if not session_id:
                return
            self.sync_ctx.add_permission(session_id, payload)

        def on_permission_replied(event: EventPayload) -> None:
            payload = event.properties
            session_id = str(payload.get("session_id") or "")
            request_id = str(payload.get("request_id") or "")
            if not session_id or not request_id:
                return
            self.sync_ctx.remove_permission(session_id, request_id)

        def on_question_asked(event: EventPayload) -> None:
            payload = event.properties
            session_id = str(payload.get("session_id") or "")
            if not session_id:
                return
            self.sync_ctx.add_question(session_id, payload)

        def on_question_resolved(event: EventPayload) -> None:
            payload = event.properties
            session_id = str(payload.get("session_id") or "")
            request_id = str(payload.get("request_id") or "")
            if not session_id or not request_id:
                return
            self.sync_ctx.remove_question(session_id, request_id)

        self._runtime_unsubscribers.append(Bus.subscribe(LSPUpdated, on_lsp_updated))
        self._runtime_unsubscribers.append(Bus.subscribe(PermissionAsked, on_permission_asked))
        self._runtime_unsubscribers.append(Bus.subscribe(PermissionReplied, on_permission_replied))
        self._runtime_unsubscribers.append(Bus.subscribe(QuestionAsked, on_question_asked))
        self._runtime_unsubscribers.append(Bus.subscribe(QuestionReplied, on_question_resolved))
        self._runtime_unsubscribers.append(Bus.subscribe(QuestionRejected, on_question_resolved))

    def _schedule_lsp_refresh(self) -> None:
        """Coalesce LSP refreshes so only one refresh runs at a time."""
        task = self._lsp_refresh_task
        if task and not task.done():
            return

        new_task = asyncio.create_task(self._refresh_lsp_status())
        self._lsp_refresh_task = new_task

        def clear_refresh_task(done: asyncio.Task[None]) -> None:
            if self._lsp_refresh_task is done:
                self._lsp_refresh_task = None

        new_task.add_done_callback(clear_refresh_task)

    async def _stop_runtime_subscriptions(self) -> None:
        """Unsubscribe runtime event listeners and stop inflight refresh tasks."""
        while self._runtime_unsubscribers:
            unsubscribe = self._runtime_unsubscribers.pop()
            try:
                unsubscribe()
            except Exception as e:
                log.warning("failed to unsubscribe runtime listener", {"error": str(e)})

        task = self._lsp_refresh_task
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._lsp_refresh_task = None

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

    def execute_command(
        self,
        command_id: str,
        source: str = "palette",
        argument: Optional[str] = None,
    ) -> None:
        """Execute a command and surface unavailable reasons to the user."""
        executed, reason = self.command_registry.execute(
            command_id,
            source=source,
            argument=argument,
        )
        if executed:
            return

        if reason:
            self.notify(reason, severity="warning")
            return
        self.notify("Command is not available right now.", severity="warning")

    def execute_slash_command(self, raw_input: str, source: str = "slash") -> bool:
        """Execute slash command text and return whether input was consumed."""
        parsed = parse_slash_command(raw_input)
        if not parsed:
            return False

        command = self.command_registry.get_by_slash(parsed.trigger)
        if not command:
            self.notify(f"Unknown command: /{parsed.trigger}", severity="warning")
            return True

        self.execute_command(
            command.id,
            source=source,
            argument=parsed.args or None,
        )
        return True

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

    def action_project_init(self, argument: Optional[str] = None) -> None:
        """Execute the built-in /init command template."""
        self.run_worker(self._run_init_command(argument), exclusive=False)

    async def _run_init_command(self, argument: Optional[str]) -> None:
        from ..project import Project

        project, sandbox = await Project.from_directory(self.sdk_ctx.cwd)
        prompt = render_init_prompt(worktree=sandbox, arguments=argument or "")
        self.notify("Running /init command...")
        await publish_command_executed(
            name="init",
            project_id=project.id,
            arguments=argument or "",
            session_id=self._active_session_id(),
        )
        self._dispatch_command_prompt(prompt)

    def _dispatch_command_prompt(self, prompt: str) -> None:
        """Dispatch a generated prompt into the active flow."""
        try:
            current_screen = self.screen
        except Exception:
            current_screen = None

        if isinstance(current_screen, SessionScreen):
            current_screen.submit_message(prompt)
            return

        self.route_ctx.navigate(
            SessionRoute(initial_prompt=PromptInfo(input=prompt))
        )

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

    def action_session_rename(self, title: Optional[str] = None) -> None:
        """Rename the active session."""
        self.run_worker(self._rename_session(title), exclusive=False)

    def action_session_compact(self) -> None:
        """Manually compact the active session."""
        self.run_worker(self._compact_session(), exclusive=False)

    def action_session_undo(self) -> None:
        """Undo the latest user turn in the active session."""
        self.run_worker(self._undo_session_turn(), exclusive=False)

    def action_session_redo(self) -> None:
        """Redo the most recently undone user turn in the active session."""
        self.run_worker(self._redo_session_turn(), exclusive=False)

    def clear_session_redo(self, session_id: Optional[str]) -> None:
        """Clear redo history for a session."""
        if not session_id:
            return
        self._redo_turns.pop(session_id, None)

    async def _rename_session(self, title: Optional[str]) -> None:
        from ..session import Session
        from .dialogs import InputDialog

        session_id = self._active_session_id()
        if not session_id:
            self.notify("Open a session first to rename it.", severity="warning")
            return

        next_title = (title or "").strip()
        if not next_title:
            current = self.sync_ctx.get_session(session_id) or {}
            current_title = current.get("title", "Untitled")
            result = await self.push_screen_wait(
                InputDialog(
                    title="Rename Session",
                    placeholder="Session title",
                    default_value=current_title,
                    submit_label="Rename",
                )
            )
            if result is None:
                return
            next_title = str(result).strip()

        if not next_title:
            self.notify("Session title cannot be empty.", severity="warning")
            return

        updated = await Session.update(session_id=session_id, title=next_title)
        if not updated:
            self.notify("Failed to rename session.", severity="error")
            return

        self.sync_ctx.update_session(
            {
                "id": updated.id,
                "title": updated.title or "Untitled",
                "agent": updated.agent,
                "parentID": updated.parent_id,
                "share": updated.share.model_dump() if updated.share else None,
                "time": {
                    "created": updated.time.created,
                    "updated": updated.time.updated,
                },
            }
        )
        self.notify(f"Renamed session to '{next_title}'.")

    async def _compact_session(self) -> None:
        session_id = self._active_session_id()
        if not session_id:
            self.notify("Open a session first to compact it.", severity="warning")
            return

        current_model = self.local_ctx.model.current()
        model_ref = None
        if current_model:
            model_ref = f"{current_model.provider_id}/{current_model.model_id}"

        self.notify("Compacting session...")
        try:
            result = await self.sdk_ctx.compact_session(session_id=session_id, model=model_ref)
        except Exception as exc:
            self.notify(f"Session compaction failed: {exc}", severity="error")
            return

        if result.get("error"):
            self.notify(f"Session compaction failed: {result['error']}", severity="error")
            return

        await self.sync_ctx.sync_session(session_id, force=True)
        await self._refresh_active_session_screen(session_id)
        self.notify("Session compacted.")

    async def _undo_session_turn(self) -> None:
        from ..session import Session

        session_id = self._active_session_id()
        if not session_id:
            self.notify("Open a session first to undo.", severity="warning")
            return

        sync = self.sync_ctx
        if not sync.is_session_synced(session_id):
            await sync.sync_session(session_id)

        messages = sync.get_messages(session_id)
        _, removed = split_messages_for_undo(messages)
        if not removed:
            self.notify("No user turn available to undo.", severity="warning")
            return

        message_ids = [
            str(message.get("id"))
            for message in removed
            if isinstance(message, dict) and message.get("id")
        ]
        if not message_ids:
            self.notify("Failed to identify messages to undo.", severity="error")
            return

        deleted = await Session.delete_messages(session_id, message_ids)
        if deleted <= 0:
            self.notify("Undo failed: session messages were not updated.", severity="error")
            return

        self._redo_turns.setdefault(session_id, []).append(deepcopy(removed))
        await sync.sync_session(session_id, force=True)
        await self._refresh_active_session_screen(
            session_id,
            prompt_text=extract_user_text_from_turn(removed),
        )
        self.notify("Undid the last turn. Use /redo to restore it.")

    async def _redo_session_turn(self) -> None:
        from ..session import Session, StoredMessageInfo
        from ..session.message_store import parse_part

        session_id = self._active_session_id()
        if not session_id:
            self.notify("Open a session first to redo.", severity="warning")
            return

        stack = self._redo_turns.get(session_id) or []
        if not stack:
            self.notify("Nothing to redo.", severity="warning")
            return

        turn = stack.pop()
        if not stack:
            self._redo_turns.pop(session_id, None)
        else:
            self._redo_turns[session_id] = stack

        restored = 0
        for message in turn:
            if not isinstance(message, dict):
                continue

            info_data = message.get("info")
            if isinstance(info_data, dict):
                try:
                    structured_info = StoredMessageInfo.model_validate(info_data)
                except Exception:
                    continue
                await Session.update_message(structured_info)
                for part_data in message.get("parts", []):
                    if not isinstance(part_data, dict):
                        continue
                    try:
                        parsed_part = parse_part(part_data)
                    except Exception:
                        continue
                    await Session.update_part(parsed_part)
                restored += 1
                continue

            continue

        if restored == 0:
            self.notify("Redo failed: no messages could be restored.", severity="error")
            return

        await self.sync_ctx.sync_session(session_id, force=True)
        await self._refresh_active_session_screen(session_id, prompt_text="")
        self.notify("Redid one turn.")

    async def _refresh_active_session_screen(
        self,
        session_id: str,
        prompt_text: Optional[str] = None,
    ) -> None:
        """Refresh currently visible session screen after history mutations."""
        try:
            screen = self.screen
        except Exception:
            return

        if not isinstance(screen, SessionScreen):
            return
        if screen.session_id != session_id:
            return

        await screen.refresh_history()
        if prompt_text is not None:
            screen.set_prompt_text(prompt_text)

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
        from .dialogs import InputDialog, SelectDialog

        preset_choice = await self.push_screen_wait(
            SelectDialog(
                title="Provider preset",
                options=[
                    ("Moonshot (Kimi)", "moonshot"),
                    ("Custom provider", "custom"),
                ],
            )
        )
        if preset_choice is None:
            return

        preset = _resolve_provider_preset(str(preset_choice))
        using_preset = preset is not None

        if preset:
            provider_type = preset.provider_type
            provider_id = preset.provider_id
            provider_name = preset.provider_name
            base_url = preset.base_url
            default_models = preset.default_models
        else:
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

            provider_id_raw = await self.push_screen_wait(
                InputDialog(
                    title="Provider ID",
                    placeholder="my-provider",
                    submit_label="Next",
                )
            )
            if provider_id_raw is None:
                return
            try:
                provider_id = _validate_provider_id(str(provider_id_raw))
            except ValueError as exc:
                self.notify(str(exc), severity="error")
                return

            provider_name_raw = await self.push_screen_wait(
                InputDialog(
                    title="Provider display name",
                    placeholder="Optional (defaults to provider ID)",
                    default_value=provider_id,
                    submit_label="Next",
                )
            )
            if provider_name_raw is None:
                return
            provider_name = provider_name_raw.strip() or provider_id

            base_url_raw = await self.push_screen_wait(
                InputDialog(
                    title="Base URL",
                    placeholder="https://api.example.com/v1",
                    submit_label="Next",
                )
            )
            if base_url_raw is None:
                return
            try:
                base_url = _validate_base_url(str(base_url_raw))
            except ValueError as exc:
                self.notify(str(exc), severity="error")
                return
            default_models = ""

        try:
            provider_id = _validate_provider_id(provider_id)
            base_url = _validate_base_url(base_url)
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
                default_value=default_models,
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

        try:
            await self.sdk_ctx.connect_provider(
                provider_id=provider_id,
                provider_type=str(provider_type),
                provider_name=provider_name,
                base_url=base_url,
                api_key=api_key,
                model_ids=model_ids,
            )
            await self._sync_providers()
        except Exception as exc:
            self.notify(f"Failed to connect provider: {exc}", severity="error")
            return

        if using_preset:
            self.notify(f"Connected provider '{provider_id}' via preset.")
        else:
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
        snapshot = select_runtime_status(sync=self.sync_ctx, route=self.route_ctx)

        current_model = self.local_ctx.model.current()
        model = "(auto)"
        if current_model:
            model = f"{current_model.provider_id}/{current_model.model_id}"
        agent = self.local_ctx.agent.current().get("name", "build")

        result = await self.push_screen_wait(
            StatusDialog(
                model=model,
                agent=agent,
                runtime=snapshot,
            )
        )
        if result == "refresh":
            self.action_status_view()

    def action_session_copy(self) -> None:
        """Copy the current session transcript to clipboard."""
        self.run_worker(self._copy_session_transcript(), exclusive=False)

    def action_session_toggle_actions(self) -> None:
        """Toggle tool details visibility in the session timeline."""
        visible = bool(self.kv_ctx.toggle("tool_details_visibility", True))
        label = "shown" if visible else "hidden"
        self.notify(f"Tool details {label}.")
        try:
            screen = self.screen
        except Exception:
            return
        if isinstance(screen, SessionScreen):
            screen.set_tool_details_visibility(visible)

    def action_session_toggle_thinking(self) -> None:
        """Toggle thinking visibility in the session timeline."""
        visible = bool(self.kv_ctx.toggle("thinking_visibility", True))
        label = "shown" if visible else "hidden"
        self.notify(f"Thinking {label}.")
        try:
            screen = self.screen
        except Exception:
            return
        if isinstance(screen, SessionScreen):
            screen.set_thinking_visibility(visible)

    def action_session_toggle_assistant_metadata(self) -> None:
        """Toggle assistant metadata visibility in the session timeline."""
        visible = bool(self.kv_ctx.toggle("assistant_metadata_visibility", True))
        label = "shown" if visible else "hidden"
        self.notify(f"Assistant metadata {label}.")
        try:
            screen = self.screen
        except Exception:
            return
        if isinstance(screen, SessionScreen):
            screen.set_assistant_metadata_visibility(visible)

    def action_session_toggle_timestamps(self) -> None:
        """Toggle timestamps visibility in the session timeline."""
        current = str(self.kv_ctx.get("timestamps", "hide"))
        next_value = "show" if current != "show" else "hide"
        self.kv_ctx.set("timestamps", next_value)
        label = "shown" if next_value == "show" else "hidden"
        self.notify(f"Timestamps {label}.")
        try:
            screen = self.screen
        except Exception:
            return
        if isinstance(screen, SessionScreen):
            screen.set_timestamps_visibility(next_value == "show")

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
            thinking=bool(self.kv_ctx.get("thinking_visibility", True)),
            tool_details=bool(self.kv_ctx.get("tool_details_visibility", True)),
            assistant_metadata=bool(self.kv_ctx.get("assistant_metadata_visibility", True)),
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
