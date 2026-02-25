"""Application lifecycle: bootstrap, runtime subscriptions, and status refresh.

Extracted from app.py to keep the main module focused on composition.
"""

from __future__ import annotations

import asyncio
from typing import Any, List, Optional

from ..util.log import Log

log = Log.create({"service": "tui.lifecycle"})


class LifecycleMixin:
    """Mixin providing bootstrap and runtime subscription logic for TuiApp."""

    async def _bootstrap(self) -> None:
        try:
            from ..project import Project
            from .context.local import ModelSelection

            await Project.from_directory(self.sdk_ctx.cwd)

            sessions = await self.sdk_ctx.list_sessions()
            session_dicts = []
            for session in sessions:
                time_data = session.get("time", {}) if isinstance(session.get("time"), dict) else {}
                session_dicts.append(
                    {
                        "id": session.get("id"),
                        "title": session.get("title") or "Untitled",
                        "agent": session.get("agent"),
                        "parent_id": session.get("parent_id"),
                        "share": session.get("share"),
                        "time": {
                            "created": int(time_data.get("created", 0) or 0),
                            "updated": int(time_data.get("updated", 0) or 0),
                        },
                    }
                )
            self.sync_ctx.set_sessions(session_dicts)

            provider_dicts = await self._sync_providers()

            agent_dicts = await self.sdk_ctx.list_agents()
            self.sync_ctx.set_agents(agent_dicts)
            self.local_ctx.update_agents(agent_dicts)
            preference = await self.sdk_ctx.get_current_preference()

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
                    preferred_provider_id = preference.get("provider_id")
                    preferred_model_id = preference.get("model_id")
                    if isinstance(preferred_provider_id, str) and isinstance(preferred_model_id, str):
                        preferred = ModelSelection(
                            provider_id=preferred_provider_id,
                            model_id=preferred_model_id,
                        )
                        if self.local_ctx.model.is_available(preferred):
                            selected_model = preferred

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
                if not default_agent:
                    preferred_agent = preference.get("agent")
                    if isinstance(preferred_agent, str) and preferred_agent.strip():
                        default_agent = preferred_agent.strip()
                if not default_agent and agent_dicts:
                    first_agent = agent_dicts[0]
                    if isinstance(first_agent, dict):
                        default_agent = str(first_agent.get("name") or "")
                if default_agent:
                    self.local_ctx.agent.set(default_agent)
            except Exception as e:
                log.warning("failed to set initial agent", {"error": str(e)})

            await self._persist_current_preference()
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
        provider_dicts = await self.sdk_ctx.list_providers()
        self.sync_ctx.set_providers(provider_dicts)
        self.local_ctx.update_providers(provider_dicts)
        return provider_dicts

    async def _refresh_runtime_status(self) -> None:
        try:
            mcp_status = await self.runtime.mcp.status()
            self.sync_ctx.set_mcp_status({
                name: status.model_dump()
                for name, status in mcp_status.items()
            })
        except Exception as e:
            log.warning("failed to load MCP status", {"error": str(e)})
            self.sync_ctx.set_mcp_status({})

        await self._refresh_lsp_status()

    async def _refresh_lsp_status(self) -> None:
        try:
            from ..project.instance import Instance

            lsp_status = await Instance.provide(
                directory=self.sdk_ctx.cwd,
                fn=self.runtime.lsp.status,
            )
            self.sync_ctx.set_lsp_status([item.model_dump() for item in lsp_status])
        except Exception as e:
            log.warning("failed to load LSP status", {"error": str(e)})
            self.sync_ctx.set_lsp_status([])

    def _start_runtime_subscriptions(self) -> None:
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

        def on_server_connection(data: Any) -> None:
            if not isinstance(data, dict):
                return
            state = str(data.get("state") or "")
            if state == "retrying":
                try:
                    attempt = int(data.get("attempt") or 0)
                except (TypeError, ValueError):
                    attempt = 0
                if attempt != 1:
                    return
                try:
                    delay = float(data.get("delay") or 0)
                except (TypeError, ValueError):
                    delay = 0
                self._server_retry_alert = True
                self.notify(
                    f"Server connection lost. Retrying in {delay:.2f}s.",
                    severity="warning",
                )
                return

            if state == "connected":
                if not self._server_retry_alert:
                    return
                self._server_retry_alert = False
                self.notify("Server connection restored.", severity="information")
                return

            if state != "exhausted":
                return
            self._server_retry_alert = False
            try:
                attempt = int(data.get("attempt") or 0)
            except (TypeError, ValueError):
                attempt = 0
            self.notify(
                f"Server unavailable after {attempt} retries.",
                severity="error",
            )

        self._runtime_unsubscribers.append(Bus.subscribe(LSPUpdated, on_lsp_updated))
        self._runtime_unsubscribers.append(Bus.subscribe(PermissionAsked, on_permission_asked))
        self._runtime_unsubscribers.append(Bus.subscribe(PermissionReplied, on_permission_replied))
        self._runtime_unsubscribers.append(Bus.subscribe(QuestionAsked, on_question_asked))
        self._runtime_unsubscribers.append(Bus.subscribe(QuestionReplied, on_question_resolved))
        self._runtime_unsubscribers.append(Bus.subscribe(QuestionRejected, on_question_resolved))
        self._runtime_unsubscribers.append(self.sdk_ctx.on_event("server.connection", on_server_connection))

        def bind_sdk_event(event_type: str) -> None:
            def on_event(data: Any) -> None:
                if not isinstance(data, dict):
                    return
                self.sync_ctx.apply_runtime_event(event_type, data)

            self._runtime_unsubscribers.append(self.sdk_ctx.on_event(event_type, on_event))

        bind_sdk_event("message.updated")
        bind_sdk_event("message.part.updated")
        bind_sdk_event("message.part.delta")
        bind_sdk_event("session.status")

    def _schedule_lsp_refresh(self) -> None:
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
