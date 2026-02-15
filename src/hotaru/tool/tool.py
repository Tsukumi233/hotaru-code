"""Tool framework for AI agent tools.

Provides base classes and utilities for defining tools that can be
invoked by AI agents.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generic, List, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

from .truncation import Truncate

T = TypeVar('T', bound=BaseModel)
M = TypeVar('M', bound=Dict[str, Any])


@dataclass
class ToolContext:
    """Context provided to tool execution."""
    session_id: str
    message_id: str
    agent: str
    call_id: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)
    messages: List[Dict[str, Any]] = field(default_factory=list)
    _metadata: Dict[str, Any] = field(default_factory=dict)
    _on_metadata: Optional[Callable[[Dict[str, Any]], None]] = None
    _aborted: bool = False
    _ruleset: List[Dict[str, Any]] = field(default_factory=list)

    def metadata(self, title: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Update tool metadata during execution."""
        if title:
            self._metadata["title"] = title
        if metadata:
            self._metadata.update(metadata)
        if self._on_metadata:
            self._on_metadata(dict(self._metadata))

    async def ask(
        self,
        permission: str,
        patterns: List[str],
        always: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
        tool_ref: Optional[Dict[str, str]] = None,
    ) -> None:
        """Request permission for an action.

        Delegates to Permission.ask() which blocks until the user responds.

        Args:
            permission: Permission type (e.g. "bash", "edit")
            patterns: Patterns to check (e.g. command string, file path)
            always: Patterns to remember if user chooses "always"
            metadata: Additional context for the permission dialog
            request_id: Optional explicit request id
            tool_ref: Optional explicit tool reference (message/call IDs)

        Raises:
            DeniedError: If permission is denied by configuration rule
            RejectedError: If user rejects the permission request
            CorrectedError: If user rejects with feedback
        """
        from ..permission import Permission

        resolved_tool = tool_ref
        if resolved_tool is None and self.message_id and self.call_id:
            resolved_tool = {
                "message_id": self.message_id,
                "call_id": self.call_id,
            }

        await Permission.ask(
            session_id=self.session_id,
            permission=permission,
            patterns=patterns,
            ruleset=Permission.from_config_list(self._ruleset),
            always=always,
            metadata=metadata,
            request_id=request_id,
            tool=resolved_tool,
        )

    @property
    def aborted(self) -> bool:
        """Check if the operation was aborted."""
        return self._aborted

    def abort(self) -> None:
        """Signal that the operation should be aborted."""
        self._aborted = True


@dataclass
class ToolResult:
    """Result returned from tool execution."""
    title: str
    output: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    attachments: List[Dict[str, Any]] = field(default_factory=list)


class ToolInfo(ABC, Generic[T]):
    """Base class for tool definitions.

    Tools are defined by subclassing ToolInfo and implementing
    the required methods.

    Example:
        class MyTool(ToolInfo[MyParams]):
            id = "my_tool"
            description = "Does something useful"
            parameters_type = MyParams

            async def execute(self, args: MyParams, ctx: ToolContext) -> ToolResult:
                return ToolResult(
                    title="Result",
                    output="Done!",
                    metadata={}
                )
    """

    id: str
    description: str
    parameters_type: Type[T]

    @abstractmethod
    async def execute(self, args: T, ctx: ToolContext) -> ToolResult:
        """Execute the tool with the given arguments.

        Args:
            args: Validated parameters
            ctx: Execution context

        Returns:
            ToolResult with output and metadata
        """
        raise NotImplementedError


class Tool:
    """Tool factory and registry.

    Provides utilities for defining and managing tools.
    """

    _registry: Dict[str, ToolInfo] = {}

    @classmethod
    def register(cls, tool: ToolInfo) -> None:
        """Register a tool in the registry."""
        cls._registry[tool.id] = tool

    @classmethod
    def get(cls, tool_id: str) -> Optional[ToolInfo]:
        """Get a tool by ID."""
        return cls._registry.get(tool_id)

    @classmethod
    def list(cls) -> List[ToolInfo]:
        """List all registered tools."""
        return list(cls._registry.values())

    @classmethod
    def define(
        cls,
        tool_id: str,
        description: str,
        parameters_type: Type[T],
        execute_fn: Callable[[T, ToolContext], ToolResult],
        auto_truncate: bool = True
    ) -> ToolInfo[T]:
        """Define a new tool using a function.

        Args:
            tool_id: Unique tool identifier
            description: Tool description for the AI
            parameters_type: Pydantic model for parameters
            execute_fn: Async function to execute the tool
            auto_truncate: Whether to auto-truncate output

        Returns:
            ToolInfo instance
        """
        # Capture values to avoid scoping issues in class body
        _tool_id = tool_id
        _description = description
        _parameters_type = parameters_type
        _execute_fn = execute_fn
        _auto_truncate = auto_truncate

        class FunctionalTool(ToolInfo[T]):
            id = _tool_id
            description = _description
            parameters_type = _parameters_type

            async def execute(self, args: T, ctx: ToolContext) -> ToolResult:
                # Validate parameters
                try:
                    if not isinstance(args, _parameters_type):
                        args = _parameters_type.model_validate(args)
                except ValidationError as e:
                    raise ValueError(
                        f"The {_tool_id} tool was called with invalid arguments: {e}.\n"
                        "Please rewrite the input so it satisfies the expected schema."
                    ) from e

                # Execute
                result = await _execute_fn(args, ctx)

                # Auto-truncate if needed
                if _auto_truncate and result.metadata.get("truncated") is None:
                    truncated = await Truncate.output(result.output)
                    result.output = truncated["content"]
                    result.metadata["truncated"] = truncated["truncated"]
                    if truncated["truncated"] and truncated.get("output_path"):
                        result.metadata["output_path"] = truncated["output_path"]

                return result

        tool = FunctionalTool()
        cls.register(tool)
        return tool
