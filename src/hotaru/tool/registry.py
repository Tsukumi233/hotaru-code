"""Tool registry for managing available tools.

The registry provides centralized access to all tools available to the AI.
Tools are registered at startup and can be dynamically added at runtime.

Built-in tools:
- read: Read file contents
- write: Write file contents
- edit: Edit files with search/replace
- bash: Execute shell commands
- glob: Find files by pattern
- grep: Search file contents
- skill: Load domain-specific skills

Custom tools can be registered using ToolRegistry.register().
"""

from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel

from .tool import Tool, ToolInfo, ToolContext, ToolResult
from .read import ReadTool
from .write import WriteTool
from .edit import EditTool
from .bash import BashTool
from .glob import GlobTool
from .grep import GrepTool
from .skill import SkillTool
from .task import TaskTool, build_task_description
from ..util.log import Log

log = Log.create({"service": "tool.registry"})


class ToolRegistry:
    """Registry for managing available tools.

    Provides access to all registered tools and their definitions.
    """

    _tools: Optional[Dict[str, ToolInfo]] = None
    _initialized: bool = False

    @classmethod
    def _initialize(cls) -> Dict[str, ToolInfo]:
        """Initialize the tool registry."""
        if cls._tools is not None:
            return cls._tools

        log.info("initializing tool registry")

        # Register built-in tools
        tools: Dict[str, ToolInfo] = {}

        builtin_tools = [
            ReadTool,
            WriteTool,
            EditTool,
            BashTool,
            GlobTool,
            GrepTool,
            SkillTool,
            TaskTool,
        ]

        for tool in builtin_tools:
            tools[tool.id] = tool
            log.info("registered tool", {"tool_id": tool.id})

        cls._tools = tools
        cls._initialized = True
        return tools

    @classmethod
    def get(cls, tool_id: str) -> Optional[ToolInfo]:
        """Get a tool by ID.

        Args:
            tool_id: Tool identifier

        Returns:
            ToolInfo or None if not found
        """
        tools = cls._initialize()
        return tools.get(tool_id)

    @classmethod
    def list(cls) -> List[ToolInfo]:
        """List all registered tools.

        Returns:
            List of ToolInfo
        """
        tools = cls._initialize()
        return list(tools.values())

    @classmethod
    def ids(cls) -> List[str]:
        """Get all tool IDs.

        Returns:
            List of tool IDs
        """
        tools = cls._initialize()
        return list(tools.keys())

    @classmethod
    def register(cls, tool: ToolInfo) -> None:
        """Register a custom tool.

        Args:
            tool: Tool to register
        """
        tools = cls._initialize()
        tools[tool.id] = tool
        log.info("registered custom tool", {"tool_id": tool.id})

    @classmethod
    async def get_tool_definitions(cls, caller_agent: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get tool definitions for the LLM.

        Returns:
            List of tool definitions in OpenAI format
        """
        from .skill import build_skill_description

        tools = cls._initialize()
        definitions = []

        for tool in tools.values():
            # Get JSON schema from pydantic model
            schema = tool.parameters_type.model_json_schema()

            # Remove title and description from schema (they go in the tool definition)
            schema.pop("title", None)

            description = tool.description
            if tool.id == "skill":
                try:
                    description = await build_skill_description()
                except Exception:
                    pass  # fall back to static description
            elif tool.id == "task":
                try:
                    description = await build_task_description(caller_agent=caller_agent)
                except Exception:
                    pass

            definitions.append({
                "type": "function",
                "function": {
                    "name": tool.id,
                    "description": description,
                    "parameters": schema,
                },
            })

        return definitions

    @classmethod
    def reset(cls) -> None:
        """Reset the registry."""
        cls._tools = None
        cls._initialized = False
