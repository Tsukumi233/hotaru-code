from __future__ import annotations

from typing import Any, TypedDict

JSONValue = dict[str, Any] | list[Any] | str | int | float | bool | None
JSONDict = dict[str, Any]


class SessionCreatePayload(TypedDict, total=False):
    agent: str
    model: str
    title: str


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


class ProviderConnectConfig(TypedDict):
    type: str
    name: str
    options: dict[str, Any]
    models: dict[str, dict[str, Any]]


class ProviderConnectPayload(TypedDict):
    provider_id: str
    api_key: str
    config: ProviderConnectConfig


class PermissionReplyPayload(TypedDict, total=False):
    reply: str
    message: str


class QuestionReplyPayload(TypedDict):
    answers: list[list[str]]


class PreferenceCurrentPayload(TypedDict, total=False):
    agent: str | None
    provider_id: str
    model_id: str


class StreamEvent(TypedDict, total=False):
    type: str
    data: JSONDict
    timestamp: int | float
    session_id: str
