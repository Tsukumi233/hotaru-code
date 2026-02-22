"""Structured message schema.

This module is a Python translation of OpenCode's structured message concept:
- Message "info" is stored separately from "parts".
- Parts are individually addressable (id) to support incremental updates.

Storage is implemented in :mod:`hotaru.session.session`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Literal, Optional, Sequence, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


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


_COMPACTION_USER_TEXT = "What did we do so far?"
_SUBTASK_USER_TEXT = "The following tool was executed by the user"
_INTERRUPTED_TOOL_ERROR = "[Tool execution was interrupted]"
_COMPACTED_TOOL_RESULT = "[Old tool result content cleared]"
_REASONING_TEXT_FIELD = "reasoning_text"


def _openai_text_from_parts(parts: Sequence[Part]) -> str:
    chunks: List[str] = []
    for part in parts:
        if isinstance(part, TextPart) and not part.ignored:
            chunks.append(part.text)
    return "".join(chunks)


def _reasoning_text_from_parts(parts: Sequence[Part]) -> str:
    chunks: List[str] = []
    for part in parts:
        if isinstance(part, ReasoningPart) and part.text:
            chunks.append(part.text)
    return "".join(chunks)


def to_openai_messages(
    messages: Iterable[WithParts],
    *,
    interleaved_field: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Convert stored structured messages to OpenAI-compatible chat messages.

    This is used for providers that accept OpenAI Chat Completions style.
    For Anthropic, convert with a dedicated transform.
    """

    out: List[Dict[str, Any]] = []
    for msg in messages:
        role = msg.info.role
        if role == "user":
            text = _openai_text_from_parts(msg.parts)
            if any(isinstance(part, CompactionPart) for part in msg.parts):
                text = f"{text}\n\n{_COMPACTION_USER_TEXT}" if text else _COMPACTION_USER_TEXT
            if any(isinstance(part, SubtaskPart) for part in msg.parts):
                text = f"{text}\n\n{_SUBTASK_USER_TEXT}" if text else _SUBTASK_USER_TEXT
            if text:
                out.append({"role": "user", "content": text})
            continue

        if role == "assistant":
            content = _openai_text_from_parts(msg.parts) or None
            assistant: Dict[str, Any] = {"role": "assistant", "content": content}
            reasoning_text = _reasoning_text_from_parts(msg.parts)
            if reasoning_text:
                assistant[_REASONING_TEXT_FIELD] = reasoning_text
                if interleaved_field:
                    assistant[interleaved_field] = reasoning_text

            # Represent tool calls as OpenAI tool_calls field (if any tool parts exist).
            tool_calls: List[Dict[str, Any]] = []
            tool_results: List[Dict[str, Any]] = []
            for part in msg.parts:
                if not isinstance(part, ToolPart):
                    continue
                if part.state.status in {"pending", "running", "completed", "error"}:
                    tool_calls.append(
                        {
                            "id": part.call_id,
                            "type": "function",
                            "function": {
                                "name": part.tool,
                                "arguments": part.state.raw or json.dumps(part.state.input or {}),
                            },
                        }
                    )
                    if part.state.status == "completed":
                        output_text = (
                            _COMPACTED_TOOL_RESULT
                            if part.state.time.compacted
                            else (part.state.output or "")
                        )
                        tool_results.append(
                            {
                                "role": "tool",
                                "tool_call_id": part.call_id,
                                "content": output_text,
                            }
                        )
                    elif part.state.status == "error":
                        tool_results.append(
                            {
                                "role": "tool",
                                "tool_call_id": part.call_id,
                                "content": part.state.error or "",
                            }
                        )
                    else:
                        # Prevent dangling tool calls on providers that require
                        # each tool call to have a corresponding tool result.
                        tool_results.append(
                            {
                                "role": "tool",
                                "tool_call_id": part.call_id,
                                "content": _INTERRUPTED_TOOL_ERROR,
                            }
                        )

            if tool_calls:
                assistant["tool_calls"] = tool_calls
                # Ensure interleaved field is present for tool-call messages
                if interleaved_field and interleaved_field not in assistant:
                    assistant[interleaved_field] = ""
            if assistant["content"] is not None or tool_calls:
                out.append(assistant)
                out.extend(tool_results)
            continue

        # system/tool roles are not stored as MessageInfo role today; ignore.
    return out


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
