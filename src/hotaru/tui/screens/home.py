"""Home screen with logo and prompt."""

from typing import Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import Screen

from ..commands import CommandRegistry, create_default_commands
from ..context import SyncEvent, use_local, use_route, use_sdk, use_sync
from ..context.route import HomeRoute, PromptInfo, SessionRoute
from ..state import ScreenSubscriptions, select_runtime_status
from ..widgets import AppFooter, Logo, PromptHints, PromptInput, PromptMeta
from ._helpers import build_slash_commands


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
        from ... import __version__

        slash_commands = build_slash_commands(self._command_registry)

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
