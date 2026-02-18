from __future__ import annotations

from typing import Any, TypedDict

JSONValue = dict[str, Any] | list[Any] | str | int | float | bool | None
JSONDict = dict[str, Any]


class SessionCreatePayload(TypedDict, total=False):
    agent: str
    model: str
    title: str
    cwd: str


class SessionCompactPayload(TypedDict, total=False):
    model: str
    provider_id: str
    model_id: str


class SessionUpdatePayload(TypedDict, total=False):
    title: str


class SessionDeleteMessagesPayload(TypedDict):
    message_ids: list[str]


class SessionRestoreMessagesPayload(TypedDict):
    messages: list[dict[str, Any]]


class ProviderConnectPayload(TypedDict):
    provider_id: str
    provider_type: str
    provider_name: str
    base_url: str
    api_key: str
    model_ids: list[str]


class PermissionReplyPayload(TypedDict, total=False):
    reply: str
    message: str


class QuestionReplyPayload(TypedDict):
    answers: list[list[str]]


class StreamEvent(TypedDict, total=False):
    type: str
    data: JSONDict
    timestamp: int | float
    session_id: str
