"""Action handlers for the TUI application.

Contains the ActionsMixin that provides session, navigation, model,
agent, and provider action methods, extracted from app.py.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Optional

from .context import HomeRoute, SessionRoute
from .context.route import PromptInfo
from .routes import HomeScreen, SessionScreen
from .theme import ThemeManager
from .turns import extract_user_text_from_turn, split_messages_for_undo
from .views import ViewsMixin
from ..util.log import Log

log = Log.create({"service": "tui.actions"})


class ActionsMixin(ViewsMixin):
    """Mixin providing action handlers for TuiApp."""

    # -- Theme / palette / navigation ----------------------------------------

    def action_toggle_theme(self) -> None:
        new_mode = ThemeManager.toggle_mode()
        self._apply_theme()
        self.notify(f"Switched to {new_mode} mode")

    def action_command_palette(self) -> None:
        from textual.command import CommandPalette
        self.push_screen(CommandPalette())

    def action_new_session(self) -> None:
        self.route_ctx.navigate(HomeRoute())

    def action_project_init(self, argument: Optional[str] = None) -> None:
        self.run_worker(self._run_init_command(argument), exclusive=False)

    async def _run_init_command(self, argument: Optional[str]) -> None:
        from ..command import render_init_prompt, publish_command_executed
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

    # -- Session actions -----------------------------------------------------

    def action_session_list(self) -> None:
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
            if not s.get("parent_id")
        ]

        self.push_screen(
            SessionListDialog(
                sessions=session_data,
                current_session_id=current_id
            ),
            callback=self._on_session_selected
        )

    def action_session_rename(self, title: Optional[str] = None) -> None:
        self.run_worker(self._rename_session(title), exclusive=False)

    def action_session_compact(self) -> None:
        self.run_worker(self._compact_session(), exclusive=False)

    def action_session_undo(self) -> None:
        self.run_worker(self._undo_session_turn(), exclusive=False)

    def action_session_redo(self) -> None:
        self.run_worker(self._redo_session_turn(), exclusive=False)

    def clear_session_redo(self, session_id: Optional[str]) -> None:
        if not session_id:
            return
        self._redo_turns.pop(session_id, None)

    async def _rename_session(self, title: Optional[str]) -> None:
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

        updated = await self.sdk_ctx.update_session(session_id=session_id, title=next_title)
        if not updated:
            self.notify("Failed to rename session.", severity="error")
            return

        self.sync_ctx.update_session(
            {
                "id": updated.get("id", session_id),
                "title": updated.get("title") or "Untitled",
                "agent": updated.get("agent"),
                "parent_id": updated.get("parent_id"),
                "share": updated.get("share"),
                "time": {
                    "created": (updated.get("time") or {}).get("created"),
                    "updated": (updated.get("time") or {}).get("updated"),
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

        await self.sync_ctx.sync_session(session_id, self.sdk_ctx, force=True)
        await self._refresh_active_session_screen(session_id)
        self.notify("Session compacted.")

    async def _undo_session_turn(self) -> None:
        session_id = self._active_session_id()
        if not session_id:
            self.notify("Open a session first to undo.", severity="warning")
            return

        sync = self.sync_ctx
        if not sync.is_session_synced(session_id):
            await sync.sync_session(session_id, self.sdk_ctx)

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

        deleted = await self.sdk_ctx.delete_messages(session_id, message_ids)
        if deleted <= 0:
            self.notify("Undo failed: session messages were not updated.", severity="error")
            return

        self._redo_turns.setdefault(session_id, []).append(deepcopy(removed))
        await sync.sync_session(session_id, self.sdk_ctx, force=True)
        await self._refresh_active_session_screen(
            session_id,
            prompt_text=extract_user_text_from_turn(removed),
        )
        self.notify("Undid the last turn. Use /redo to restore it.")

    async def _redo_session_turn(self) -> None:
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

        restored = await self.sdk_ctx.restore_messages(session_id, turn)

        if restored == 0:
            self.notify("Redo failed: no messages could be restored.", severity="error")
            return

        await self.sync_ctx.sync_session(session_id, self.sdk_ctx, force=True)
        await self._refresh_active_session_screen(session_id, prompt_text="")
        self.notify("Redid one turn.")

    async def _refresh_active_session_screen(
        self,
        session_id: str,
        prompt_text: Optional[str] = None,
    ) -> None:
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
        if result is None:
            return

        action, session_id = result
        if action == "select" and session_id:
            self.route_ctx.navigate(SessionRoute(session_id=session_id))
        elif action == "new":
            self.route_ctx.navigate(HomeRoute())

    # -- Model / provider / agent actions ------------------------------------

    def action_model_list(self, provider_filter: Optional[str] = None) -> None:
        from .dialogs import ModelSelectDialog

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
        from .providers import provider_connect_flow
        self.run_worker(provider_connect_flow(self), exclusive=False)

    def action_agent_list(self) -> None:
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
        if not agent_name:
            return

        if self.local_ctx.agent.set(agent_name):
            self.run_worker(self._persist_current_preference(), exclusive=False)
            self.notify(f"Switched to {agent_name}")
            return
        self.notify(f"Agent '{agent_name}' is unavailable", severity="warning")

    def _on_model_selected(self, result) -> None:
        if result is None:
            return

        provider_id, model_id = result
        from .context.local import ModelSelection
        self.local_ctx.model.set(
            ModelSelection(provider_id=provider_id, model_id=model_id),
            add_to_recent=True
        )
        self.run_worker(self._persist_current_preference(), exclusive=False)
        self.notify(f"Switched to {provider_id}/{model_id}")

    async def _persist_current_preference(self) -> None:
        try:
            payload: dict[str, Any] = {}
            current = self.local_ctx.model.current()
            if current:
                payload["provider_id"] = current.provider_id
                payload["model_id"] = current.model_id
            agent = self.local_ctx.agent.current().get("name")
            if isinstance(agent, str) and agent.strip():
                payload["agent"] = agent.strip()
            if payload:
                await self.sdk_ctx.update_current_preference(payload)
        except Exception as e:
            log.warning("failed to persist current preference", {"error": str(e)})

    def action_quit(self) -> None:
        self.exit()


def register_default_commands(app) -> None:
    """Wire up default commands to their action handlers on the app."""
    from .commands import create_default_commands

    _MAP = {
        "app.exit": lambda s="palette", a=None: app.exit(),
        "session.new": lambda s="palette", a=None: app.action_new_session(),
        "session.list": lambda s="palette", a=None: app.action_session_list(),
        "session.share": lambda s="palette", a=None: app.action_session_share(),
        "session.undo": lambda s="palette", a=None: app.action_session_undo(),
        "session.redo": lambda s="palette", a=None: app.action_session_redo(),
        "session.compact": lambda s="palette", a=None: app.action_session_compact(),
        "session.export": lambda s="palette", a=None: app.action_session_export(),
        "session.copy": lambda s="palette", a=None: app.action_session_copy(),
        "session.toggle.actions": lambda s="palette", a=None: app.action_session_toggle_actions(),
        "session.toggle.thinking": lambda s="palette", a=None: app.action_session_toggle_thinking(),
        "session.toggle.assistant_metadata": lambda s="palette", a=None: app.action_session_toggle_assistant_metadata(),
        "session.toggle.timestamps": lambda s="palette", a=None: app.action_session_toggle_timestamps(),
        "agent.list": lambda s="palette", a=None: app.action_agent_list(),
        "help.show": lambda s="palette", a=None: app._show_help(),
    }

    for command in create_default_commands():
        if command.id in _MAP:
            command.on_select = _MAP[command.id]
        elif command.id in ("theme.toggle_mode", "theme.switch"):
            command.on_select = lambda s="palette", a=None: app.action_toggle_theme()
        elif command.id == "project.init":
            command.on_select = lambda s="palette", a=None: app.action_project_init(a)
        elif command.id == "session.rename":
            command.on_select = lambda s="palette", a=None: app.action_session_rename(a)
        elif command.id == "provider.connect":
            command.on_select = lambda s="palette", a=None: app.action_provider_connect()
        elif command.id == "model.list":
            command.on_select = lambda s="palette", a=None: app.action_model_list(provider_filter=a or None)
        elif command.id in ("mcp.list", "status.view"):
            command.on_select = lambda s="palette", a=None: app.action_status_view()

        app.command_registry.register(command)
