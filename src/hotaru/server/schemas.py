"""Pydantic schemas for the FastAPI transport layer."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ErrorInfo(BaseModel):
    code: str
    message: str
    details: dict[str, object] | list[object] | str | None = None


class ErrorResponse(BaseModel):
    error: ErrorInfo


class HealthResponse(BaseModel):
    status: str = "ok"


class WebReadyResponse(BaseModel):
    ready: bool


class WebHealthResponse(BaseModel):
    status: str = "ok"
    web: WebReadyResponse


class PathsResponse(BaseModel):
    home: str
    state: str
    config: str
    cwd: str


class SkillResponse(BaseModel):
    name: str
    description: str
    location: str


class SessionTimeResponse(BaseModel):
    created: int
    updated: int


class SessionResponse(BaseModel):
    id: str
    project_id: str | None = None
    agent: str | None = None
    model_id: str | None = None
    provider_id: str | None = None
    directory: str | None = None
    parent_id: str | None = None
    time: SessionTimeResponse | None = None

    model_config = ConfigDict(extra="allow")


class SessionCreateRequest(BaseModel):
    project_id: str | None = None
    parent_id: str | None = None
    agent: str | None = None
    model: str | None = None
    provider_id: str | None = None
    model_id: str | None = None
    directory: str | None = None
    cwd: str | None = None

    model_config = ConfigDict(extra="allow")


class SessionUpdateRequest(BaseModel):
    title: str | None = None

    model_config = ConfigDict(extra="allow")


class SessionMessageRequest(BaseModel):
    content: str | None = None
    parts: list[dict[str, object]] | None = None
    metadata: dict[str, object] | None = None

    model_config = ConfigDict(extra="allow")


class SessionCompactRequest(BaseModel):
    auto: bool = False
    model: str | None = None
    provider_id: str | None = None
    model_id: str | None = None

    model_config = ConfigDict(extra="allow")


class SessionDeleteMessagesRequest(BaseModel):
    message_ids: list[str]

    model_config = ConfigDict(extra="allow")


class SessionRestoreMessagesRequest(BaseModel):
    messages: list[dict[str, object]]

    model_config = ConfigDict(extra="allow")


class SessionMessageResponse(BaseModel):
    ok: bool
    assistant_message_id: str | None = None
    status: str | None = None
    error: object | None = None

    model_config = ConfigDict(extra="allow")


class SessionDeleteResponse(BaseModel):
    ok: bool


class SessionDeleteMessagesResponse(BaseModel):
    deleted: int


class SessionRestoreMessagesResponse(BaseModel):
    restored: int


class SessionListMessageResponse(BaseModel):
    id: str
    role: str
    info: dict[str, object] = Field(default_factory=dict)
    metadata: dict[str, object] = Field(default_factory=dict)
    parts: list[dict[str, object]] = Field(default_factory=list)


class ProviderResponse(BaseModel):
    id: str
    name: str
    source: str | None = None
    model_count: int = 0


class ProviderModelResponse(BaseModel):
    id: str
    name: str | None = None
    api_id: str | None = None
    status: object | None = None


class ProviderConnectRequest(BaseModel):
    provider_id: str | None = None
    api_key: str | None = None
    config: dict[str, object] | None = None

    model_config = ConfigDict(extra="allow")


class ProviderConnectResponse(BaseModel):
    ok: bool
    provider_id: str
    provider: ProviderResponse | None = None


class AgentResponse(BaseModel):
    name: str
    description: str = ""
    mode: str = "primary"
    hidden: bool = False


class PreferenceCurrentResponse(BaseModel):
    agent: str | None = None
    provider_id: str | None = None
    model_id: str | None = None


class PreferenceCurrentUpdateRequest(BaseModel):
    agent: str | None = None
    provider_id: str | None = None
    model_id: str | None = None

    model_config = ConfigDict(extra="allow")


class PermissionReplyRequest(BaseModel):
    reply: Literal["once", "always", "reject"]
    message: str | None = None


class QuestionReplyRequest(BaseModel):
    answers: list[list[str]]


class SseEnvelope(BaseModel):
    type: str
    data: dict[str, object]
    timestamp: int
    session_id: str | None = None
