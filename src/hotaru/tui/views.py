"""View-related action handlers for the TUI application.

Contains the ViewsMixin that provides status, toggle, transcript,
export, share, and clipboard actions, extracted from app.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .routes import SessionScreen
from .state import select_runtime_status
from .transcript import TranscriptOptions, format_transcript


class ViewsMixin:
    """Mixin providing view/display action handlers for TuiApp."""

    # -- Status view ---------------------------------------------------------

    def action_status_view(self) -> None:
        self.run_worker(self._show_status_dialog(), exclusive=False)

    async def _show_status_dialog(self) -> None:
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

    # -- Toggle actions ------------------------------------------------------

    def action_session_copy(self) -> None:
        self.run_worker(self._copy_session_transcript(), exclusive=False)

    def action_session_toggle_actions(self) -> None:
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

    # -- Transcript / share / export -----------------------------------------

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

    # -- Helpers -------------------------------------------------------------

    def _active_session_id(self) -> Optional[str]:
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
        sync = self.sync_ctx
        if not sync.is_session_synced(session_id):
            await sync.sync_session(session_id, self.sdk_ctx)

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
        try:
            self.copy_to_clipboard(text)
            return True
        except Exception:
            return False
