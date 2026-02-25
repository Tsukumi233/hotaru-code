"""Main TUI application.

This module provides the main Textual application class for the
Hotaru Code terminal user interface.
"""

import asyncio
from textual.app import App, ComposeResult
from textual.widgets import Footer
from textual.command import Provider, Hit, Hits
from typing import Any, Callable, Dict, List, Optional

from .actions import ActionsMixin, register_default_commands
from .bindings import APP_BINDINGS
from .lifecycle import LifecycleMixin
from .providers import (
    validate_provider_id as _validate_provider_id,
    validate_base_url as _validate_base_url,
    parse_model_ids as _parse_model_ids,
    resolve_preset as _resolve_provider_preset,
)
from .routes import HomeScreen, SessionScreen
from .theme import ThemeManager
from .commands import CommandRegistry, Command
from .input_parsing import parse_slash_command
from .context import (
    RouteProvider, HomeRoute, SessionRoute,
    ArgsProvider, Args,
    KVProvider,
    LocalProvider,
    SyncProvider,
)
from .context.route import PromptInfo
from ..util.log import Log
from ..runtime import AppContext

log = Log.create({"service": "tui.app"})


class HotaruCommandProvider(Provider):
    """Command provider for the command palette."""

    @property
    def commands(self) -> List[Command]:
        app = self.app
        if isinstance(app, TuiApp):
            return app.command_registry.list_commands()
        return []

    async def search(self, query: str) -> Hits:
        query = query.lower()
        app = self.app
        if not isinstance(app, TuiApp):
            return

        for command in self.commands:
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

            if command.slash_name and query in command.slash_name.lower():
                help_text = f"/{command.slash_name}"
                if not command.enabled and command.availability_reason:
                    help_text = f"{help_text} ({command.availability_reason})"
                yield Hit(
                    command.title,
                    lambda cid=command.id: app.execute_command(cid, source="palette"),
                    help=help_text,
                )


class TuiApp(LifecycleMixin, ActionsMixin, App):
    """Main TUI application for Hotaru Code."""

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

    BINDINGS = APP_BINDINGS
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
        super().__init__(**kwargs)

        self.session_id = session_id
        self.initial_prompt = initial_prompt
        self.model = model
        self.agent = agent
        self.continue_session = continue_session

        self._init_contexts()

        self.command_registry = CommandRegistry()
        register_default_commands(self)
        self._redo_turns: Dict[str, List[List[Dict[str, Any]]]] = {}
        self._runtime_unsubscribers: List[Callable[[], None]] = []
        self._lsp_refresh_task: Optional[asyncio.Task[None]] = None
        self._server_retry_alert = False
        self.runtime: AppContext = AppContext()

        ThemeManager.load_preference()
        self._apply_theme()

        log.info("TUI app initialized", {
            "session_id": session_id,
            "model": model,
            "agent": agent,
            "continue_session": continue_session,
        })

    def _init_contexts(self) -> None:
        self.args_ctx = ArgsProvider.provide(Args(
            model=self.model,
            agent=self.agent,
            session_id=self.session_id,
            continue_session=self.continue_session,
            prompt=self.initial_prompt,
        ))
        self.kv_ctx = KVProvider.provide()
        self.route_ctx = RouteProvider.provide()
        from .context import SDKProvider
        self.sdk_ctx = SDKProvider.provide()
        self.sync_ctx = SyncProvider.provide()
        self.local_ctx = LocalProvider.provide()
        self.route_ctx.on_change(self._on_route_change)

    def _on_route_change(self, route) -> None:
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

    def _apply_theme(self) -> None:
        self.dark = ThemeManager.get_mode() == "dark"

    def _show_help(self) -> None:
        from .dialogs import HelpDialog
        self.push_screen(HelpDialog())

    def compose(self) -> ComposeResult:
        yield Footer()

    async def on_mount(self) -> None:
        await self.runtime.startup()
        await self.sdk_ctx.start_event_stream()
        await self._bootstrap()
        self._start_runtime_subscriptions()

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

        self.route_ctx._route = initial_route
        self.push_screen(self._build_screen_for_route(initial_route))

    async def on_unmount(self) -> None:
        await self._stop_runtime_subscriptions()
        await self.sdk_ctx.aclose()

        try:
            await self.runtime.shutdown()
        except Exception as e:
            log.warning("failed to shutdown runtime", {"error": str(e)})

    def _build_screen_for_route(self, route):
        if route.type == "session":
            return SessionScreen(
                session_id=route.session_id,
                initial_message=route.initial_prompt.input if route.initial_prompt else None
            )
        return HomeScreen(
            initial_prompt=route.initial_prompt.input if route.initial_prompt else None
        )

    def _continue_last_session(self):
        sessions = self.sync_ctx.data.sessions
        if sessions:
            for session in sorted(
                sessions,
                key=lambda s: s.get("time", {}).get("updated", 0),
                reverse=True,
            ):
                if not session.get("parent_id"):
                    return SessionRoute(session_id=session["id"])

        return HomeRoute()

    def execute_command(
        self,
        command_id: str,
        source: str = "palette",
        argument: Optional[str] = None,
    ) -> None:
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

    async def show_toast(
        self,
        message: str,
        variant: str = "info",
        title: Optional[str] = None,
        duration: float = 5.0
    ) -> None:
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
    app = TuiApp(
        session_id=session_id,
        initial_prompt=initial_prompt,
        model=model,
        agent=agent,
        continue_session=continue_session,
    )
    app.run()


async def run_tui_async(
    session_id: Optional[str] = None,
    initial_prompt: Optional[str] = None,
    model: Optional[str] = None,
    agent: Optional[str] = None,
    continue_session: bool = False,
) -> None:
    app = TuiApp(
        session_id=session_id,
        initial_prompt=initial_prompt,
        model=model,
        agent=agent,
        continue_session=continue_session,
    )
    await app.run_async()
