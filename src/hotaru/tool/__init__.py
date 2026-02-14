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
    "ToolRegistry",
]
