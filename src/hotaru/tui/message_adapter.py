"""Adapters between structured session messages and TUI-friendly payloads."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from ..session.message_store import (
    CompactionPart,
    FilePart,
    PatchPart,
    ReasoningPart,
    StepFinishPart,
    StepStartPart,
    SubtaskPart,
    TextPart,
    ToolPart,
    WithParts,
)


def structured_messages_to_tui(messages: Iterable[WithParts]) -> List[Dict[str, Any]]:
    """Convert structured session messages into TUI message dictionaries."""
    return [structured_message_to_tui(message) for message in messages]


def structured_message_to_tui(message: WithParts) -> Dict[str, Any]:
    """Convert a single structured message into a TUI message dictionary."""
    info = message.info
    metadata: Dict[str, Any] = {
        "time": {
            "created": info.time.created,
            "completed": info.time.completed,
        }
    }

    if info.role == "assistant":
        assistant_meta: Dict[str, Any] = {}
        if info.model:
            assistant_meta["provider_id"] = info.model.provider_id
            assistant_meta["model_id"] = info.model.model_id
        if info.agent:
            assistant_meta["agent"] = info.agent
        if assistant_meta:
            metadata["assistant"] = assistant_meta

        metadata["usage"] = {
            "input_tokens": int(info.tokens.input or 0),
            "output_tokens": int(info.tokens.output or 0),
            "reasoning_tokens": int(info.tokens.reasoning or 0),
            "cache_read_tokens": int(info.tokens.cache_read or 0),
            "cache_write_tokens": int(info.tokens.cache_write or 0),
        }
        metadata["cost"] = float(info.cost or 0.0)
        if info.summary is not None:
            metadata["summary"] = bool(info.summary)
        if info.finish:
            metadata["finish"] = info.finish

    if info.error:
        metadata["error"] = dict(info.error)

    return {
        "id": info.id,
        "role": info.role,
        "info": info.model_dump(mode="json"),
        "metadata": metadata,
        "parts": [_part_to_tui(part) for part in message.parts],
    }


def _part_to_tui(part: Any) -> Dict[str, Any]:
    if isinstance(part, TextPart):
        return {
            "id": part.id,
            "session_id": part.session_id,
            "message_id": part.message_id,
            "type": part.type,
            "text": part.text,
            "synthetic": part.synthetic,
            "ignored": part.ignored,
            "metadata": dict(part.metadata or {}),
        }

    if isinstance(part, ReasoningPart):
        return {
            "id": part.id,
            "session_id": part.session_id,
            "message_id": part.message_id,
            "type": part.type,
            "text": part.text,
            "metadata": dict(part.metadata or {}),
        }

    if isinstance(part, ToolPart):
        state = part.state.model_dump(mode="json")
        return {
            "id": part.id,
            "session_id": part.session_id,
            "message_id": part.message_id,
            "type": part.type,
            "tool": part.tool,
            "call_id": part.call_id,
            "state": state,
        }

    if isinstance(part, FilePart):
        return {
            "id": part.id,
            "session_id": part.session_id,
            "message_id": part.message_id,
            "type": part.type,
            "mime": part.mime,
            "media_type": part.mime,
            "url": part.url,
            "filename": part.filename,
            "source": dict(part.source or {}),
        }

    if isinstance(part, StepStartPart):
        return {
            "id": part.id,
            "session_id": part.session_id,
            "message_id": part.message_id,
            "type": part.type,
            "snapshot": part.snapshot,
        }

    if isinstance(part, StepFinishPart):
        return {
            "id": part.id,
            "session_id": part.session_id,
            "message_id": part.message_id,
            "type": part.type,
            "reason": part.reason,
            "snapshot": part.snapshot,
            "cost": float(part.cost or 0.0),
            "tokens": part.tokens.model_dump(mode="json"),
        }

    if isinstance(part, PatchPart):
        return {
            "id": part.id,
            "session_id": part.session_id,
            "message_id": part.message_id,
            "type": part.type,
            "hash": part.hash,
            "files": list(part.files or []),
        }

    if isinstance(part, CompactionPart):
        return {
            "id": part.id,
            "session_id": part.session_id,
            "message_id": part.message_id,
            "type": part.type,
            "auto": part.auto,
        }

    if isinstance(part, SubtaskPart):
        return {
            "id": part.id,
            "session_id": part.session_id,
            "message_id": part.message_id,
            "type": part.type,
            "prompt": part.prompt,
            "description": part.description,
            "agent": part.agent,
            "model": part.model.model_dump(mode="json") if part.model else None,
            "command": part.command,
        }

    return {}
