from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

import httpx

from .types import (
    PermissionReplyPayload,
    PreferenceCurrentPayload,
    ProviderConnectPayload,
    QuestionReplyPayload,
    SessionCompactPayload,
    SessionCreatePayload,
    SessionDeleteMessagesPayload,
    SessionRestoreMessagesPayload,
    SessionUpdatePayload,
)


class ApiClientError(RuntimeError):
    """Raised when an API call fails."""

    def __init__(
        self,
        status_code: int,
        message: str,
        payload: Any | None = None,
        path: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload
        self.path = path


class HotaruAPIClient:
    """Typed HTTP client for the Hotaru /v1 contract."""

    def __init__(
        self,
        *,
        base_url: str,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
        headers: dict[str, str] | None = None,
        directory: str | None = None,
    ) -> None:
        request_headers: dict[str, str] = dict(headers or {})
        if directory:
            request_headers["x-hotaru-directory"] = self._encode_directory_header(directory)

        self._client = client or httpx.AsyncClient(
            base_url=base_url,
            transport=transport,
            timeout=timeout,
            headers=request_headers or None,
        )

        if client is not None and request_headers:
            self._client.headers.update(request_headers)

    @staticmethod
    def _encode_directory_header(directory: str) -> str:
        value = str(directory)
        is_non_ascii = any(ord(ch) > 127 for ch in value)
        return quote(value) if is_non_ascii else value

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | list[Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        response = await self._client.request(method, path, json=json_body, params=params)

        self._raise_for_status(response)
        if response.status_code == 204 or not response.content:
            return None

        try:
            return response.json()
        except ValueError:
            return {"value": response.text}

    async def _stream_request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | list[Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        request = self._client.build_request(method, path, json=json_body, params=params)
        response = await self._client.send(request, stream=True)

        self._raise_for_status(response)
        return response

    @staticmethod
    def _extract_error_message(payload: Any, fallback: str) -> str:
        if isinstance(payload, dict):
            err = payload.get("error")
            if isinstance(err, dict):
                message = err.get("message")
                if isinstance(message, str) and message.strip():
                    return message
            if isinstance(err, str) and err.strip():
                return err
            message = payload.get("message")
            if isinstance(message, str) and message.strip():
                return message
        return fallback

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.is_success:
            return

        payload: Any | None
        try:
            payload = response.json()
        except ValueError:
            payload = response.text

        message = self._extract_error_message(
            payload,
            f"HTTP {response.status_code} for {response.request.method} {response.request.url.path}",
        )
        raise ApiClientError(
            status_code=response.status_code,
            message=message,
            payload=payload,
            path=response.request.url.path,
        )

    @staticmethod
    def _iter_stream_payload_lines(line: str) -> str | None:
        value = line.strip()
        if not value or value.startswith(":"):
            return None
        if value.startswith("event:"):
            return None
        if value.startswith("data:"):
            value = value[5:].strip()
        if not value or value == "[DONE]":
            return None
        return value

    async def _iter_stream_events(self, response: httpx.Response) -> AsyncIterator[dict[str, Any]]:
        async for line in response.aiter_lines():
            payload_line = self._iter_stream_payload_lines(line)
            if payload_line is None:
                continue
            try:
                payload = json.loads(payload_line)
            except json.JSONDecodeError:
                continue

            if isinstance(payload, dict):
                yield payload
            else:
                yield {"type": "message.event", "data": {"value": payload}}

    async def create_session(self, payload: SessionCreatePayload | dict[str, Any] | None = None) -> dict[str, Any]:
        result = await self._request_json(
            "POST",
            "/v1/sessions",
            json_body=dict(payload or {}),
        )
        return result if isinstance(result, dict) else {}

    async def list_sessions(self, project_id: str | None = None) -> list[dict[str, Any]]:
        params = {"project_id": project_id} if project_id else None
        result = await self._request_json(
            "GET",
            "/v1/sessions",
            params=params,
        )
        return result if isinstance(result, list) else []

    async def get_session(self, session_id: str) -> dict[str, Any]:
        result = await self._request_json(
            "GET",
            f"/v1/sessions/{session_id}",
        )
        return result if isinstance(result, dict) else {}

    async def update_session(
        self,
        session_id: str,
        payload: SessionUpdatePayload | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = await self._request_json(
            "PATCH",
            f"/v1/sessions/{session_id}",
            json_body=dict(payload or {}),
        )
        return result if isinstance(result, dict) else {}

    async def delete_session(self, session_id: str) -> None:
        await self._request_json(
            "DELETE",
            f"/v1/sessions/{session_id}",
        )

    async def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        result = await self._request_json(
            "GET",
            f"/v1/sessions/{session_id}/messages",
        )
        return result if isinstance(result, list) else []

    async def delete_messages(
        self,
        session_id: str,
        payload: SessionDeleteMessagesPayload | dict[str, Any],
    ) -> int:
        result = await self._request_json(
            "DELETE",
            f"/v1/sessions/{session_id}/messages",
            json_body=dict(payload),
        )
        if isinstance(result, dict):
            return int(result.get("deleted", 0) or 0)
        return 0

    async def restore_messages(
        self,
        session_id: str,
        payload: SessionRestoreMessagesPayload | dict[str, Any],
    ) -> int:
        result = await self._request_json(
            "POST",
            f"/v1/sessions/{session_id}/messages/restore",
            json_body=dict(payload),
        )
        if isinstance(result, dict):
            return int(result.get("restored", 0) or 0)
        return 0

    async def send_session_message(
        self,
        session_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        result = await self._request_json(
            "POST",
            f"/v1/sessions/{session_id}/messages",
            json_body=payload,
        )
        return result if isinstance(result, dict) else {}

    async def interrupt_session(self, session_id: str) -> dict[str, Any]:
        result = await self._request_json(
            "POST",
            f"/v1/sessions/{session_id}/interrupt",
        )
        return result if isinstance(result, dict) else {}

    async def stream_events(self) -> AsyncIterator[dict[str, Any]]:
        response = await self._stream_request(
            "GET",
            "/v1/events",
        )
        try:
            async for event in self._iter_stream_events(response):
                yield event
        finally:
            await response.aclose()

    async def compact_session(
        self,
        session_id: str,
        payload: SessionCompactPayload | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = await self._request_json(
            "POST",
            f"/v1/sessions/{session_id}/compact",
            json_body=dict(payload or {}),
        )
        return result if isinstance(result, dict) else {}

    async def list_providers(self) -> list[dict[str, Any]]:
        result = await self._request_json(
            "GET",
            "/v1/providers",
        )
        return result if isinstance(result, list) else []

    async def list_provider_models(self, provider_id: str) -> list[dict[str, Any]]:
        result = await self._request_json(
            "GET",
            f"/v1/providers/{provider_id}/models",
        )
        return result if isinstance(result, list) else []

    async def connect_provider(self, payload: ProviderConnectPayload | dict[str, Any]) -> dict[str, Any]:
        result = await self._request_json(
            "POST",
            "/v1/providers/connect",
            json_body=dict(payload),
        )
        return result if isinstance(result, dict) else {"ok": bool(result)}

    async def list_agents(self) -> list[dict[str, Any]]:
        result = await self._request_json(
            "GET",
            "/v1/agents",
        )
        return result if isinstance(result, list) else []

    async def get_current_preference(self) -> dict[str, Any]:
        result = await self._request_json(
            "GET",
            "/v1/preferences/current",
        )
        return result if isinstance(result, dict) else {}

    async def update_current_preference(
        self,
        payload: PreferenceCurrentPayload | dict[str, Any],
    ) -> dict[str, Any]:
        result = await self._request_json(
            "PATCH",
            "/v1/preferences/current",
            json_body=dict(payload),
        )
        return result if isinstance(result, dict) else {}

    async def list_permissions(self) -> list[dict[str, Any]]:
        result = await self._request_json(
            "GET",
            "/v1/permissions",
        )
        return result if isinstance(result, list) else []

    async def reply_permission(
        self,
        request_id: str,
        reply: str,
        message: str | None = None,
    ) -> bool:
        payload: PermissionReplyPayload = {"reply": reply}
        if message:
            payload["message"] = message
        result = await self._request_json(
            "POST",
            f"/v1/permissions/{request_id}/reply",
            json_body=payload,
        )
        return bool(result)

    async def list_questions(self) -> list[dict[str, Any]]:
        result = await self._request_json(
            "GET",
            "/v1/questions",
        )
        return result if isinstance(result, list) else []

    async def reply_question(self, request_id: str, answers: list[list[str]]) -> bool:
        payload: QuestionReplyPayload = {"answers": answers}
        result = await self._request_json(
            "POST",
            f"/v1/questions/{request_id}/reply",
            json_body=payload,
        )
        return bool(result)

    async def reject_question(self, request_id: str) -> bool:
        result = await self._request_json(
            "POST",
            f"/v1/questions/{request_id}/reject",
        )
        return bool(result)

    async def get_paths(self) -> dict[str, Any]:
        result = await self._request_json(
            "GET",
            "/v1/path",
        )
        return result if isinstance(result, dict) else {}
