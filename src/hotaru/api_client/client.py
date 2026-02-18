from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

import httpx

from .types import (
    PermissionReplyPayload,
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
            "/v1/session",
            json_body=dict(payload or {}),
        )
        return result if isinstance(result, dict) else {}

    async def list_sessions(self, project_id: str | None = None) -> list[dict[str, Any]]:
        params = {"project_id": project_id} if project_id else None
        result = await self._request_json(
            "GET",
            "/v1/session",
            params=params,
        )
        return result if isinstance(result, list) else []

    async def get_session(self, session_id: str) -> dict[str, Any]:
        result = await self._request_json(
            "GET",
            f"/v1/session/{session_id}",
        )
        return result if isinstance(result, dict) else {}

    async def update_session(
        self,
        session_id: str,
        payload: SessionUpdatePayload | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = await self._request_json(
            "PATCH",
            f"/v1/session/{session_id}",
            json_body=dict(payload or {}),
        )
        return result if isinstance(result, dict) else {}

    async def delete_session(self, session_id: str) -> None:
        await self._request_json(
            "DELETE",
            f"/v1/session/{session_id}",
        )

    async def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        result = await self._request_json(
            "GET",
            f"/v1/session/{session_id}/message",
        )
        return result if isinstance(result, list) else []

    async def delete_messages(
        self,
        session_id: str,
        payload: SessionDeleteMessagesPayload | dict[str, Any],
    ) -> int:
        result = await self._request_json(
            "POST",
            f"/v1/session/{session_id}/message:delete",
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
            f"/v1/session/{session_id}/message:restore",
            json_body=dict(payload),
        )
        if isinstance(result, dict):
            return int(result.get("restored", 0) or 0)
        return 0

    async def stream_session_message(
        self,
        session_id: str,
        payload: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        response = await self._stream_request(
            "POST",
            f"/v1/session/{session_id}/message:stream",
            json_body=payload,
        )

        try:
            async for event in self._iter_stream_events(response):
                yield event
        finally:
            await response.aclose()

    async def stream_events(self) -> AsyncIterator[dict[str, Any]]:
        response = await self._stream_request(
            "GET",
            "/v1/event",
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
            f"/v1/session/{session_id}/compact",
            json_body=dict(payload or {}),
        )
        return result if isinstance(result, dict) else {}

    async def list_providers(self) -> list[dict[str, Any]]:
        result = await self._request_json(
            "GET",
            "/v1/provider",
        )
        return result if isinstance(result, list) else []

    async def list_provider_models(self, provider_id: str) -> list[dict[str, Any]]:
        result = await self._request_json(
            "GET",
            f"/v1/provider/{provider_id}/model",
        )
        return result if isinstance(result, list) else []

    async def connect_provider(self, payload: ProviderConnectPayload | dict[str, Any]) -> dict[str, Any]:
        request_payload = self._normalize_provider_connect_payload(dict(payload))
        result = await self._request_json(
            "POST",
            "/v1/provider/connect",
            json_body=request_payload,
        )
        return result if isinstance(result, dict) else {"ok": bool(result)}

    @staticmethod
    def _normalize_provider_connect_payload(payload: dict[str, Any]) -> dict[str, Any]:
        if "config" in payload:
            return payload

        provider_id = payload.get("provider_id") or payload.get("providerID")
        api_key = payload.get("api_key") or payload.get("apiKey")
        provider_type = payload.get("provider_type") or payload.get("providerType")
        provider_name = payload.get("provider_name") or payload.get("providerName") or provider_id
        base_url = payload.get("base_url") or payload.get("baseURL")
        model_ids = payload.get("model_ids") or payload.get("modelIDs") or []

        if not isinstance(provider_id, str):
            return payload
        if not isinstance(api_key, str):
            return payload
        if not isinstance(provider_type, str):
            return payload
        if not isinstance(provider_name, str):
            return payload
        if not isinstance(base_url, str):
            return payload
        if not isinstance(model_ids, list):
            return payload

        normalized_model_ids = [str(item).strip() for item in model_ids if str(item).strip()]
        models = {model_id: {"name": model_id} for model_id in normalized_model_ids}

        return {
            "provider_id": provider_id,
            "api_key": api_key,
            "config": {
                "type": provider_type,
                "name": provider_name,
                "options": {"baseURL": base_url},
                "models": models,
            },
        }

    async def list_agents(self) -> list[dict[str, Any]]:
        result = await self._request_json(
            "GET",
            "/v1/agent",
        )
        return result if isinstance(result, list) else []

    async def list_permissions(self) -> list[dict[str, Any]]:
        result = await self._request_json(
            "GET",
            "/v1/permission",
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
            f"/v1/permission/{request_id}/reply",
            json_body=payload,
        )
        return bool(result)

    async def list_questions(self) -> list[dict[str, Any]]:
        result = await self._request_json(
            "GET",
            "/v1/question",
        )
        return result if isinstance(result, list) else []

    async def reply_question(self, request_id: str, answers: list[list[str]]) -> bool:
        payload: QuestionReplyPayload = {"answers": answers}
        result = await self._request_json(
            "POST",
            f"/v1/question/{request_id}/reply",
            json_body=payload,
        )
        return bool(result)

    async def reject_question(self, request_id: str) -> bool:
        result = await self._request_json(
            "POST",
            f"/v1/question/{request_id}/reject",
        )
        return bool(result)

    async def get_paths(self) -> dict[str, Any]:
        result = await self._request_json(
            "GET",
            "/v1/path",
        )
        return result if isinstance(result, dict) else {}
