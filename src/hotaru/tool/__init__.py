"""Tool system modules with lazy exports to avoid import cycles."""

from __future__ import annotations

from importlib import import_module
from typing import Dict, Tuple

from .tool import Tool, ToolContext, ToolResult, ToolInfo
from .truncation import Truncate

_EXPORTS: Dict[str, Tuple[str, str]] = {
    "ReadTool": (".read", "ReadTool"),
    "WriteTool": (".write", "WriteTool"),
    "EditTool": (".edit", "EditTool"),
    "BashTool": (".bash", "BashTool"),
    "GlobTool": (".glob", "GlobTool"),
    "GrepTool": (".grep", "GrepTool"),
    "LsTool": (".list", "LsTool"),
    "SkillTool": (".skill", "SkillTool"),
    "TaskTool": (".task", "TaskTool"),
    "QuestionTool": (".question", "QuestionTool"),
    "TodoWriteTool": (".todo", "TodoWriteTool"),
    "TodoReadTool": (".todo", "TodoReadTool"),
    "WebFetchTool": (".webfetch", "WebFetchTool"),
    "WebSearchTool": (".websearch", "WebSearchTool"),
    "CodeSearchTool": (".codesearch", "CodeSearchTool"),
    "ApplyPatchTool": (".apply_patch", "ApplyPatchTool"),
    "MultiEditTool": (".multiedit", "MultiEditTool"),
    "BatchTool": (".batch", "BatchTool"),
    "PlanEnterTool": (".plan", "PlanEnterTool"),
    "PlanExitTool": (".plan", "PlanExitTool"),
    "LspTool": (".lsp", "LspTool"),
    "ToolRegistry": (".registry", "ToolRegistry"),
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


__all__ = [
    "Tool",
    "ToolContext",
    "ToolResult",
    "ToolInfo",
    "Truncate",
    *_EXPORTS.keys(),
]
