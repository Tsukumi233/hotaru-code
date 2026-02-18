"""Session management modules with lazy exports to avoid import cycles."""

from __future__ import annotations

from importlib import import_module
from typing import Dict, Tuple

_EXPORTS: Dict[str, Tuple[str, str]] = {
    "Session": (".session", "Session"),
    "SessionInfo": (".session", "SessionInfo"),
    "MessageUpdated": (".session", "MessageUpdated"),
    "MessageUpdatedProperties": (".session", "MessageUpdatedProperties"),
    "MessagePartUpdated": (".session", "MessagePartUpdated"),
    "MessagePartUpdatedProperties": (".session", "MessagePartUpdatedProperties"),
    "MessagePartDelta": (".session", "MessagePartDelta"),
    "MessagePartDeltaProperties": (".session", "MessagePartDeltaProperties"),
    "SessionStatus": (".session", "SessionStatus"),
    "SessionStatusProperties": (".session", "SessionStatusProperties"),
    "LLM": (".llm", "LLM"),
    "StreamInput": (".llm", "StreamInput"),
    "StreamChunk": (".llm", "StreamChunk"),
    "StreamResult": (".llm", "StreamResult"),
    "SessionProcessor": (".processor", "SessionProcessor"),
    "ProcessorResult": (".processor", "ProcessorResult"),
    "SystemPrompt": (".system", "SystemPrompt"),
    "InstructionPrompt": (".instruction", "InstructionPrompt"),
    "Todo": (".todo", "Todo"),
    "TodoInfo": (".todo", "TodoInfo"),
    "TodoUpdated": (".todo", "TodoUpdated"),
    "TodoUpdatedProperties": (".todo", "TodoUpdatedProperties"),
    "StoredMessageInfo": (".message_store", "MessageInfo"),
    "StoredMessageWithParts": (".message_store", "WithParts"),
    "StoredMessagePart": (".message_store", "Part"),
    "SessionPrompt": (".prompting", "SessionPrompt"),
    "PromptResult": (".prompting", "PromptResult"),
    "SessionCompaction": (".compaction", "SessionCompaction"),
    "SessionSummary": (".summary", "SessionSummary"),
}


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if not target:
        raise AttributeError(name)

    module_name, attr_name = target
    module = import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


__all__ = list(_EXPORTS.keys())
