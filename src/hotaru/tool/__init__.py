"""Tool system modules.

This module provides the tool framework for AI agent capabilities.
Tools are functions that the AI can invoke to interact with the system.

Built-in tools:
- ReadTool: Read file contents
- WriteTool: Write file contents
- EditTool: Edit files with search/replace
- BashTool: Execute shell commands
- GlobTool: Find files by pattern
- GrepTool: Search file contents
- ListTool: List files as a tree
- SkillTool: Load domain-specific skills

Example:
    from hotaru.tool import ToolRegistry

    # Get all available tools
    tools = ToolRegistry.list()

    # Get tool definitions for LLM (async)
    definitions = await ToolRegistry.get_tool_definitions()
"""

from .tool import Tool, ToolContext, ToolResult, ToolInfo
from .truncation import Truncate
from .read import ReadTool
from .write import WriteTool
from .edit import EditTool
from .bash import BashTool
from .glob import GlobTool
from .grep import GrepTool
from .list import ListTool
from .skill import SkillTool
from .task import TaskTool
from .question import QuestionTool
from .todo import TodoWriteTool, TodoReadTool
from .webfetch import WebFetchTool
from .websearch import WebSearchTool
from .codesearch import CodeSearchTool
from .apply_patch import ApplyPatchTool
from .multiedit import MultiEditTool
from .batch import BatchTool
from .invalid import InvalidTool
from .plan import PlanEnterTool, PlanExitTool
from .lsp import LspTool
from .registry import ToolRegistry

__all__ = [
    "Tool",
    "ToolContext",
    "ToolResult",
    "ToolInfo",
    "Truncate",
    "ReadTool",
    "WriteTool",
    "EditTool",
    "BashTool",
    "GlobTool",
    "GrepTool",
    "ListTool",
    "SkillTool",
    "TaskTool",
    "QuestionTool",
    "TodoWriteTool",
    "TodoReadTool",
    "WebFetchTool",
    "WebSearchTool",
    "CodeSearchTool",
    "ApplyPatchTool",
    "MultiEditTool",
    "BatchTool",
    "InvalidTool",
    "PlanEnterTool",
    "PlanExitTool",
    "LspTool",
    "ToolRegistry",
]
