"""Session management modules with lazy exports to avoid import cycles."""

from __future__ import annotations

from importlib import import_module
from typing import Dict, Tuple

_EXPORTS: Dict[str, Tuple[str, str]] = {
    "Message": (".message", "Message"),
    "MessageInfo": (".message", "MessageInfo"),
    "MessagePart": (".message", "MessagePart"),
    "TextPart": (".message", "TextPart"),
    "ReasoningPart": (".message", "ReasoningPart"),
    "ToolInvocationPart": (".message", "ToolInvocationPart"),
    "ToolCall": (".message", "ToolCall"),
    "ToolResult": (".message", "ToolResult"),
    "FilePart": (".message", "FilePart"),
    "Session": (".session", "Session"),
    "SessionInfo": (".session", "SessionInfo"),
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
