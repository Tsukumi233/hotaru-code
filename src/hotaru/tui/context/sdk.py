"""SDK context for TUI <-> API communication."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from collections.abc import AsyncIterator, Callable
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from ...api_client import ApiClientError, HotaruAPIClient
from ...util.log import Log

log = Log.create({"service": "tui.context.sdk"})
_DEFAULT_API_BASE_URL = "http://127.0.0.1:4096"
_EVENT_STREAM_BASE_DELAY = 0.25
_EVENT_STREAM_MAX_DELAY = 30.0
_EVENT_STREAM_BACKOFF = 2.0
_EVENT_STREAM_MAX_RETRIES = 50
_SEND_MESSAGE_IDLE_TIMEOUT = 60.0


def _event_stream_delay(attempt: int) -> float:
    turn = max(int(attempt), 1)
    backoff = _EVENT_STREAM_BASE_DELAY * (_EVENT_STREAM_BACKOFF ** (turn - 1))
    return min(backoff, _EVENT_STREAM_MAX_DELAY)


class SDKContext:
    """TUI SDK context backed by the versioned API client."""

    def __init__(
        self,
        cwd: str | None = None,
        api_client: Any | None = None,
    ) -> None:
        self._cwd = cwd or str(Path.cwd())
        self._event_handlers: dict[str, list[Callable[[dict[str, Any]], None]]] = {}
        self._owns_api_client = api_client is None
        self._api_client = api_client or self._build_default_api_client(self._cwd)
        self._event_task: asyncio.Task[None] | None = None
        self._event_stream_ready = asyncio.Event()

    @staticmethod
    def _build_default_api_client(cwd: str) -> HotaruAPIClient:
        return HotaruAPIClient(
            base_url=_DEFAULT_API_BASE_URL,
            directory=cwd,
        )

    @property
    def cwd(self) -> str:
        return self._cwd

    async def aclose(self) -> None:
        await self.stop_event_stream()
        if self._owns_api_client and hasattr(self._api_client, "aclose"):
            await self._api_client.aclose()

    def _supports_event_stream(self) -> bool:
        return hasattr(self._api_client, "stream_events")

    def _emit_connection_state(
        self,
        state: str,
        attempt: int | None = None,
        delay: float | None = None,
        error: str | None = None,
    ) -> None:
        data: dict[str, Any] = {"state": state}
        if attempt is not None:
            data["attempt"] = attempt
        if delay is not None:
            data["delay"] = delay
        if error:
            data["error"] = error
        self.emit_event("server.connection", data)

    async def _run_event_stream(self) -> None:
        if not self._supports_event_stream():
            return

        attempt = 0
        while True:
            self._event_stream_ready.clear()
            try:
                async for event in self._api_client.stream_events():
                    if not isinstance(event, dict):
                        continue
                    if not self._event_stream_ready.is_set():
                        if attempt > 0:
                            log.info("event stream recovered", {"attempt": attempt})
                        attempt = 0
                        self._event_stream_ready.set()
                        self._emit_connection_state("connected")
                    event_type = str(event.get("type", "server.event"))
                    data = event.get("data", {})
                    if not isinstance(data, dict):
                        data = {"value": data}
                    self.emit_event(event_type, data)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                attempt += 1
                delay = _event_stream_delay(attempt)
                error = str(exc)
                if attempt == 1:
                    log.warning(
                        "event stream failed",
                        {"error": error, "retry_in": delay},
                    )
                else:
                    log.debug(
                        "event stream retry scheduled",
                        {"attempt": attempt, "retry_in": delay},
                    )
                self._emit_connection_state(
                    "retrying",
                    attempt=attempt,
                    delay=delay,
                    error=error,
                )
                if attempt >= _EVENT_STREAM_MAX_RETRIES:
                    log.error("event stream retries exhausted", {"attempt": attempt})
                    self._emit_connection_state("exhausted", attempt=attempt)
                    return
                await asyncio.sleep(delay)
            else:
                attempt += 1
                delay = _event_stream_delay(attempt)
                if attempt == 1:
                    log.warning("event stream closed", {"retry_in": delay})
                else:
                    log.debug(
                        "event stream closed, retry scheduled",
                        {"attempt": attempt, "retry_in": delay},
                    )
                self._emit_connection_state(
                    "retrying",
                    attempt=attempt,
                    delay=delay,
                    error="stream closed",
                )
                if attempt >= _EVENT_STREAM_MAX_RETRIES:
                    log.error("event stream retries exhausted", {"attempt": attempt})
                    self._emit_connection_state("exhausted", attempt=attempt)
                    return
                await asyncio.sleep(delay)

    def _ensure_event_stream_started(self) -> None:
        if not self._supports_event_stream():
            return
        if self._event_task is not None and not self._event_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._event_task = loop.create_task(self._run_event_stream())

    async def start_event_stream(self) -> None:
        self._ensure_event_stream_started()
        if self._event_task is not None:
            try:
                await asyncio.wait_for(self._event_stream_ready.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                log.warning("event stream not ready before timeout")

    async def stop_event_stream(self) -> None:
        task = self._event_task
        self._event_task = None
        self._event_stream_ready.clear()
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    @staticmethod
    def _split_model_ref(model: str) -> tuple[str, str]:
        provider_id, _, model_id = str(model).partition("/")
        provider_id = provider_id.strip()
        model_id = model_id.strip()
        if not provider_id or not model_id:
            raise ValueError("Model must be in 'provider/model' format")
        return provider_id, model_id

    @staticmethod
    def _as_non_empty_string(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("Value cannot be empty")
        return text

    async def send_message(
        self,
        session_id: str,
        content: str,
        agent: str | None = None,
        model: str | None = None,
        files: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        payload: dict[str, Any] = {"content": content}
        if agent:
            payload["agent"] = agent
        if model:
            payload["model"] = model
        if files:
            payload["files"] = files

        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        idle_reached = asyncio.Event()
        unsubscribers: list[Callable[[], None]] = []
        trigger_task: asyncio.Task[dict[str, Any]] | None = None
        idle_grace_deadline: float | None = None

        def _extract_session_id(data: dict[str, Any]) -> str:
            value = data.get("session_id")
            if isinstance(value, str) and value:
                return value
            return ""

        def _on_message_updated(data: dict[str, Any]) -> None:
            info = data.get("info")
            if not isinstance(info, dict):
                return
            if _extract_session_id(info) != session_id:
                return
            queue.put_nowait({"type": "message.updated", "data": {"info": info}})

        def _on_part_updated(data: dict[str, Any]) -> None:
            part = data.get("part")
            if not isinstance(part, dict):
                return
            if _extract_session_id(part) != session_id:
                return
            queue.put_nowait({"type": "message.part.updated", "data": {"part": part}})

        def _on_part_delta(data: dict[str, Any]) -> None:
            if _extract_session_id(data) != session_id:
                return
            queue.put_nowait({"type": "message.part.delta", "data": dict(data)})

        def _on_session_status(data: dict[str, Any]) -> None:
            if _extract_session_id(data) != session_id:
                return
            status = data.get("status") if isinstance(data.get("status"), dict) else {}
            queue.put_nowait({"type": "session.status", "data": dict(data)})
            if str(status.get("type") or "") == "idle":
                idle_reached.set()

        unsubscribers.append(self.on_event("message.updated", _on_message_updated))
        unsubscribers.append(self.on_event("message.part.updated", _on_part_updated))
        unsubscribers.append(self.on_event("message.part.delta", _on_part_delta))
        unsubscribers.append(self.on_event("session.status", _on_session_status))

        try:
            await self.start_event_stream()
            trigger_task = asyncio.create_task(self._api_client.send_session_message(session_id, payload))
            while True:
                if trigger_task.done():
                    exc = trigger_task.exception()
                    if exc:
                        yield {"type": "error", "data": {"error": str(exc)}}
                        break
                    if idle_reached.is_set() and queue.empty():
                        break

                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.1)
                except asyncio.TimeoutError:
                    if trigger_task.done():
                        exc = trigger_task.exception()
                        if exc:
                            yield {"type": "error", "data": {"error": str(exc)}}
                            break
                        if idle_reached.is_set() and queue.empty():
                            break
                        if queue.empty():
                            loop = asyncio.get_running_loop()
                            now = loop.time()
                            if idle_grace_deadline is None:
                                idle_grace_deadline = now + _SEND_MESSAGE_IDLE_TIMEOUT
                                continue
                            if now >= idle_grace_deadline:
                                break
                    continue

                idle_grace_deadline = None
                yield event
        except Exception as exc:
            yield {"type": "error", "data": {"error": str(exc)}}
        finally:
            for unsubscribe in unsubscribers:
                try:
                    unsubscribe()
                except Exception:
                    pass
            if trigger_task is not None and not trigger_task.done():
                trigger_task.cancel()
                with suppress(asyncio.CancelledError):
                    await trigger_task

    async def create_session(
        self,
        agent: str | None = None,
        model: str | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if agent:
            payload["agent"] = agent
        if model:
            payload["model"] = model
        if title:
            payload["title"] = title

        return await self._api_client.create_session(payload)

    async def compact_session(
        self,
        session_id: str,
        model: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if model:
            provider_id, model_id = self._split_model_ref(model)
            payload["model"] = model
            payload["provider_id"] = provider_id
            payload["model_id"] = model_id
        return await self._api_client.compact_session(session_id, payload)

    async def interrupt(self, session_id: str) -> dict[str, Any]:
        return await self._api_client.interrupt_session(session_id)

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        try:
            session = await self._api_client.get_session(session_id)
        except ApiClientError as exc:
            if exc.status_code == 404:
                return None
            raise
        return session

    async def update_session(self, session_id: str, *, title: str | None = None) -> dict[str, Any] | None:
        payload: dict[str, Any] = {}
        if title is not None:
            payload["title"] = str(title)
        try:
            session = await self._api_client.update_session(session_id, payload)
        except ApiClientError as exc:
            if exc.status_code == 404:
                return None
            raise
        return session

    async def list_sessions(self, project_id: str | None = None) -> list[dict[str, Any]]:
        return await self._api_client.list_sessions(project_id=project_id)

    async def delete_session(self, session_id: str) -> None:
        await self._api_client.delete_session(session_id)

    async def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        try:
            return await self._api_client.list_messages(session_id)
        except ApiClientError as exc:
            if exc.status_code == 404:
                return []
            raise

    async def delete_messages(self, session_id: str, message_ids: list[str]) -> int:
        try:
            return await self._api_client.delete_messages(
                session_id,
                {"message_ids": [str(item) for item in message_ids]},
            )
        except ApiClientError as exc:
            if exc.status_code == 404:
                return 0
            raise

    async def restore_messages(self, session_id: str, messages: list[dict[str, Any]]) -> int:
        try:
            return await self._api_client.restore_messages(
                session_id,
                {"messages": messages},
            )
        except ApiClientError as exc:
            if exc.status_code == 404:
                return 0
            raise

    @staticmethod
    def _normalize_provider_models(models: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        normalized: dict[str, dict[str, Any]] = {}
        for model in models:
            if not isinstance(model, dict):
                continue

            model_id = str(model.get("id") or "").strip()
            if not model_id:
                continue

            limit = model.get("limit") if isinstance(model.get("limit"), dict) else {}
            context_limit = int(limit.get("context", 0) or 0)
            output_limit = int(limit.get("output", 0) or 0)

            normalized[model_id] = {
                "id": model_id,
                "name": str(model.get("name") or model_id),
                "api_id": str(model.get("api_id") or model.get("apiID") or model_id),
                "limit": {
                    "context": context_limit,
                    "output": output_limit,
                },
            }
        return normalized

    async def list_providers(self) -> list[dict[str, Any]]:
        providers = await self._api_client.list_providers()
        result: list[dict[str, Any]] = []

        for provider in providers:
            if not isinstance(provider, dict):
                continue
            provider_id = str(provider.get("id") or "").strip()
            if not provider_id:
                continue

            raw_models = provider.get("models")
            model_items: list[dict[str, Any]]
            if isinstance(raw_models, list):
                model_items = [item for item in raw_models if isinstance(item, dict)]
            elif isinstance(raw_models, dict):
                model_items = [
                    {"id": key, **value}
                    for key, value in raw_models.items()
                    if isinstance(value, dict)
                ]
            else:
                model_items = []

            if not model_items:
                try:
                    model_items = await self._api_client.list_provider_models(provider_id)
                except ApiClientError as exc:
                    if exc.status_code != 404:
                        raise
                    model_items = []

            result.append(
                {
                    "id": provider_id,
                    "name": str(provider.get("name") or provider_id),
                    "models": self._normalize_provider_models(model_items),
                }
            )

        return result

    async def list_mcp_status(self) -> dict[str, dict[str, Any]]:
        if not hasattr(self._api_client, "list_mcp_status"):
            return {}
        result = await self._api_client.list_mcp_status()
        return result if isinstance(result, dict) else {}

    async def mcp_connect(self, name: str) -> dict[str, Any]:
        if not hasattr(self._api_client, "mcp_connect"):
            return {"ok": False}
        result = await self._api_client.mcp_connect(name)
        return result if isinstance(result, dict) else {"ok": bool(result)}

    async def mcp_disconnect(self, name: str) -> dict[str, Any]:
        if not hasattr(self._api_client, "mcp_disconnect"):
            return {"ok": False}
        result = await self._api_client.mcp_disconnect(name)
        return result if isinstance(result, dict) else {"ok": bool(result)}

    async def mcp_auth_start(self, name: str) -> dict[str, Any]:
        if not hasattr(self._api_client, "mcp_auth_start"):
            return {}
        result = await self._api_client.mcp_auth_start(name)
        return result if isinstance(result, dict) else {}

    async def mcp_auth_callback(self, name: str, code: str, state: str) -> dict[str, Any]:
        if not hasattr(self._api_client, "mcp_auth_callback"):
            return {}
        result = await self._api_client.mcp_auth_callback(name, {"code": code, "state": state})
        return result if isinstance(result, dict) else {}

    async def mcp_auth_authenticate(self, name: str) -> dict[str, Any]:
        if not hasattr(self._api_client, "mcp_auth_authenticate"):
            return {}
        result = await self._api_client.mcp_auth_authenticate(name)
        return result if isinstance(result, dict) else {}

    async def mcp_auth_remove(self, name: str) -> dict[str, Any]:
        if not hasattr(self._api_client, "mcp_auth_remove"):
            return {"ok": False}
        result = await self._api_client.mcp_auth_remove(name)
        return result if isinstance(result, dict) else {"ok": bool(result)}

    async def connect_provider(
        self,
        provider_id: str,
        provider_type: str,
        provider_name: str,
        base_url: str,
        api_key: str,
        model_ids: list[str],
    ) -> dict[str, Any]:
        normalized_provider_id = self._as_non_empty_string(provider_id).lower()
        normalized_provider_type = self._as_non_empty_string(provider_type)
        normalized_provider_name = self._as_non_empty_string(provider_name)
        normalized_base_url = self._as_non_empty_string(base_url)
        normalized_api_key = self._as_non_empty_string(api_key)

        normalized_models: list[str] = []
        seen: set[str] = set()
        for item in model_ids:
            model_id = str(item).strip()
            if not model_id or model_id in seen:
                continue
            seen.add(model_id)
            normalized_models.append(model_id)
        if not normalized_models:
            raise ValueError("At least one model ID is required")

        models = {model_id: {"name": model_id} for model_id in normalized_models}
        payload = {
            "provider_id": normalized_provider_id,
            "api_key": normalized_api_key,
            "config": {
                "type": normalized_provider_type,
                "name": normalized_provider_name,
                "options": {"baseURL": normalized_base_url},
                "models": models,
            },
        }
        result = await self._api_client.connect_provider(payload)
        return result if isinstance(result, dict) else {"ok": bool(result)}

    async def list_agents(self) -> list[dict[str, Any]]:
        return await self._api_client.list_agents()

    async def get_current_preference(self) -> dict[str, Any]:
        if not hasattr(self._api_client, "get_current_preference"):
            return {}
        result = await self._api_client.get_current_preference()
        return result if isinstance(result, dict) else {}

    async def update_current_preference(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not hasattr(self._api_client, "update_current_preference"):
            return {}
        result = await self._api_client.update_current_preference(payload)
        return result if isinstance(result, dict) else {}

    async def list_permissions(self) -> list[dict[str, Any]]:
        return await self._api_client.list_permissions()

    async def reply_permission(
        self,
        request_id: str,
        reply: str,
        message: str | None = None,
    ) -> bool:
        return await self._api_client.reply_permission(request_id, reply, message)

    async def list_questions(self) -> list[dict[str, Any]]:
        return await self._api_client.list_questions()

    async def reply_question(self, request_id: str, answers: list[list[str]]) -> bool:
        return await self._api_client.reply_question(request_id, answers)

    async def reject_question(self, request_id: str) -> bool:
        return await self._api_client.reject_question(request_id)

    async def get_paths(self) -> dict[str, Any]:
        return await self._api_client.get_paths()

    def on_event(self, event_type: str, handler: Callable[[dict[str, Any]], None]) -> Callable[[], None]:
        if event_type not in self._event_handlers:
            self._event_handlers[event_type] = []
        self._event_handlers[event_type].append(handler)

        def unsubscribe() -> None:
            if event_type in self._event_handlers and handler in self._event_handlers[event_type]:
                self._event_handlers[event_type].remove(handler)

        return unsubscribe

    def emit_event(self, event_type: str, data: dict[str, Any]) -> None:
        if event_type not in self._event_handlers:
            return
        for handler in self._event_handlers[event_type]:
            try:
                handler(data)
            except Exception as exc:
                log.error(
                    "event handler error",
                    {
                        "event_type": event_type,
                        "error": str(exc),
                    },
                )


_sdk_context: ContextVar[SDKContext | None] = ContextVar("sdk_context", default=None)


class SDKProvider:
    """Provider for SDK context."""

    _instance: SDKContext | None = None

    @classmethod
    def get(cls) -> SDKContext:
        ctx = _sdk_context.get()
        if ctx is None:
            ctx = SDKContext()
            _sdk_context.set(ctx)
            cls._instance = ctx
        return ctx

    @classmethod
    def provide(
        cls,
        cwd: str | None = None,
        api_client: Any | None = None,
    ) -> SDKContext:
        ctx = SDKContext(cwd=cwd, api_client=api_client)
        _sdk_context.set(ctx)
        cls._instance = ctx
        return ctx

    @classmethod
    def reset(cls) -> None:
        _sdk_context.set(None)
        cls._instance = None


def use_sdk() -> SDKContext:
    return SDKProvider.get()
