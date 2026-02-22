"""Structured message schema.

This module is a Python translation of OpenCode's structured message concept:
- Message "info" is stored separately from "parts".
- Parts are individually addressable (id) to support incremental updates.

Storage is implemented in :mod:`hotaru.session.session`.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Literal, Optional, Sequence, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from ..provider.transform import ProviderTransform

Role = Literal["user", "assistant", "tool", "system"]
FinishReason = Literal["stop", "tool-calls", "length", "content_filter", "unknown"]


class ModelRef(BaseModel):
    provider_id: str
    model_id: str


class MessageTime(BaseModel):
    created: int
    completed: Optional[int] = None


class TokenUsage(BaseModel):
    input: int = 0
    output: int = 0
    reasoning: int = 0
    cache_read: int = 0
    cache_write: int = 0
    total: Optional[int] = None


class PathInfo(BaseModel):
    cwd: str
    root: str


class MessageInfo(BaseModel):
    """Message metadata record (without parts)."""

    id: str
    session_id: str
    role: Role
    time: MessageTime

    # Threading
    parent_id: Optional[str] = None

    # LLM selection and behavior
    agent: Optional[str] = None
    mode: Optional[str] = None
    model: Optional[ModelRef] = None
    variant: Optional[str] = None
    system: Optional[str] = None
    tools: Optional[Dict[str, bool]] = None
    format: Optional[Dict[str, Any]] = None

    # Assistant-only fields (best-effort; some providers may not supply all)
    finish: Optional[FinishReason] = None
    error: Optional[Dict[str, Any]] = None
    cost: float = 0.0
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    path: Optional[PathInfo] = None
    summary: Optional[bool] = None
    structured: Optional[Any] = None

    model_config = ConfigDict(extra="allow")


class PartTime(BaseModel):
    start: int
    end: Optional[int] = None


class PartBase(BaseModel):
    id: str
    session_id: str
    message_id: str


class TextPart(PartBase):
    type: Literal["text"] = "text"
    text: str
    synthetic: bool = False
    ignored: bool = False
    time: Optional[PartTime] = None
    metadata: Optional[Dict[str, Any]] = None


class ReasoningPart(PartBase):
    type: Literal["reasoning"] = "reasoning"
    text: str
    time: PartTime
    metadata: Optional[Dict[str, Any]] = None


class FilePart(PartBase):
    type: Literal["file"] = "file"
    mime: str
    url: str
    filename: Optional[str] = None
    source: Optional[Dict[str, Any]] = None


class StepStartPart(PartBase):
    type: Literal["step-start"] = "step-start"
    snapshot: Optional[str] = None


class StepFinishPart(PartBase):
    type: Literal["step-finish"] = "step-finish"
    reason: str
    snapshot: Optional[str] = None
    cost: float = 0.0
    tokens: TokenUsage = Field(default_factory=TokenUsage)


class PatchPart(PartBase):
    type: Literal["patch"] = "patch"
    hash: str
    files: List[str] = Field(default_factory=list)


class ToolStateTime(BaseModel):
    start: int
    end: Optional[int] = None
    compacted: Optional[int] = None


class ToolState(BaseModel):
    status: Literal["pending", "running", "completed", "error"] = "pending"
    input: Dict[str, Any] = Field(default_factory=dict)
    raw: str = ""
    output: Optional[str] = None
    error: Optional[str] = None
    title: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    attachments: List[Dict[str, Any]] = Field(default_factory=list)
    time: ToolStateTime


class ToolPart(PartBase):
    type: Literal["tool"] = "tool"
    tool: str
    call_id: str
    state: ToolState
    metadata: Optional[Dict[str, Any]] = None


class CompactionPart(PartBase):
    type: Literal["compaction"] = "compaction"
    auto: bool = False


class SubtaskPart(PartBase):
    type: Literal["subtask"] = "subtask"
    prompt: str
    description: str
    agent: str
    model: Optional[ModelRef] = None
    command: Optional[str] = None


Part = Union[
    TextPart,
    ReasoningPart,
    ToolPart,
    FilePart,
    StepStartPart,
    StepFinishPart,
    PatchPart,
    CompactionPart,
    SubtaskPart,
]

PART_ADAPTER = TypeAdapter(Part)


@dataclass(frozen=True)
class WithParts:
    info: MessageInfo
    parts: List[Part]


def to_openai_messages(
    messages: Iterable[WithParts],
    *,
    interleaved_field: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Convert stored structured messages to OpenAI-compatible chat messages.

    This is used for providers that accept OpenAI Chat Completions style.
    For Anthropic, convert with a dedicated transform.
    """

    return ProviderTransform.from_structured_messages(
        messages,
        interleaved_field=interleaved_field,
    )


def to_model_messages(
    messages: Iterable[WithParts],
    *,
    interleaved_field: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Alias used by the session loop when building provider input messages."""
    return to_openai_messages(messages, interleaved_field=interleaved_field)


def filter_compacted(messages: Sequence[WithParts]) -> List[WithParts]:
    """Return only messages after the newest completed compaction boundary."""
    if not messages:
        return []

    compacted_user_ids = {
        msg.info.parent_id
        for msg in messages
        if msg.info.role == "assistant"
        and msg.info.summary is True
        and bool(msg.info.finish)
        and bool(msg.info.parent_id)
    }
    compacted_user_ids = {item for item in compacted_user_ids if item}

    start_index = 0
    for idx, msg in enumerate(messages):
        if msg.info.role != "user":
            continue
        if msg.info.id not in compacted_user_ids:
            continue
        if any(isinstance(part, CompactionPart) for part in msg.parts):
            start_index = idx

    if start_index <= 0:
        return list(messages)
    return list(messages[start_index:])


def parse_part(data: Dict[str, Any]) -> Part:
    """Parse a persisted dict into a concrete Part instance."""
    return PART_ADAPTER.validate_python(data)
