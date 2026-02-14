"""Message types for session conversations.

Defines the structure of messages exchanged between users and AI agents.
"""

from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field


class TextPart(BaseModel):
    """Text content part."""
    type: Literal["text"] = "text"
    text: str


class ReasoningPart(BaseModel):
    """Reasoning/thinking content part."""
    type: Literal["reasoning"] = "reasoning"
    text: str
    provider_metadata: Optional[Dict[str, Any]] = None


class ToolCallState(str, Enum):
    """State of a tool invocation."""
    CALL = "call"
    PARTIAL_CALL = "partial-call"
    RESULT = "result"


class ToolCall(BaseModel):
    """A tool call invocation."""
    state: Literal["call"] = "call"
    step: Optional[int] = None
    tool_call_id: str
    tool_name: str
    args: Any


class ToolPartialCall(BaseModel):
    """A partial tool call (streaming)."""
    state: Literal["partial-call"] = "partial-call"
    step: Optional[int] = None
    tool_call_id: str
    tool_name: str
    args: Any


class ToolResult(BaseModel):
    """Result of a tool call."""
    state: Literal["result"] = "result"
    step: Optional[int] = None
    tool_call_id: str
    tool_name: str
    args: Any
    result: str


ToolInvocation = Union[ToolCall, ToolPartialCall, ToolResult]


class ToolInvocationPart(BaseModel):
    """Tool invocation content part."""
    type: Literal["tool-invocation"] = "tool-invocation"
    tool_invocation: ToolInvocation


class SourceUrlPart(BaseModel):
    """Source URL reference part."""
    type: Literal["source-url"] = "source-url"
    source_id: str
    url: str
    title: Optional[str] = None
    provider_metadata: Optional[Dict[str, Any]] = None


class FilePart(BaseModel):
    """File attachment part."""
    type: Literal["file"] = "file"
    media_type: str
    filename: Optional[str] = None
    url: str


class StepStartPart(BaseModel):
    """Step start marker."""
    type: Literal["step-start"] = "step-start"


MessagePart = Union[TextPart, ReasoningPart, ToolInvocationPart, SourceUrlPart, FilePart, StepStartPart]


class MessageRole(str, Enum):
    """Role of a message sender."""
    USER = "user"
    ASSISTANT = "assistant"


class TokenUsage(BaseModel):
    """Token usage statistics."""
    input: int = 0
    output: int = 0
    reasoning: int = 0
    cache_read: int = 0
    cache_write: int = 0


class MessageTime(BaseModel):
    """Message timing information."""
    created: int
    completed: Optional[int] = None


class ToolMetadata(BaseModel):
    """Metadata for a tool invocation."""
    title: str
    snapshot: Optional[str] = None
    time_start: int
    time_end: int

    class Config:
        extra = "allow"


class PathInfo(BaseModel):
    """Path context for a message."""
    cwd: str
    root: str


class AssistantMetadata(BaseModel):
    """Metadata specific to assistant messages."""
    system: List[str] = Field(default_factory=list)
    model_id: str
    provider_id: str
    path: PathInfo
    cost: float = 0.0
    summary: Optional[bool] = None
    tokens: TokenUsage = Field(default_factory=TokenUsage)


class MessageMetadata(BaseModel):
    """Metadata for a message."""
    time: MessageTime
    session_id: str
    error: Optional[Dict[str, Any]] = None
    tool: Dict[str, ToolMetadata] = Field(default_factory=dict)
    assistant: Optional[AssistantMetadata] = None
    snapshot: Optional[str] = None


class MessageInfo(BaseModel):
    """Complete message information."""
    id: str
    role: MessageRole
    parts: List[MessagePart] = Field(default_factory=list)
    metadata: MessageMetadata

    class Config:
        use_enum_values = True


class Message:
    """Message utilities and factory methods."""

    @staticmethod
    def create_user(
        message_id: str,
        session_id: str,
        text: str,
        created: int
    ) -> MessageInfo:
        """Create a user message.

        Args:
            message_id: Unique message ID
            session_id: Session ID
            text: Message text
            created: Creation timestamp (ms)

        Returns:
            MessageInfo for the user message
        """
        return MessageInfo(
            id=message_id,
            role=MessageRole.USER,
            parts=[TextPart(text=text)],
            metadata=MessageMetadata(
                time=MessageTime(created=created, completed=created),
                session_id=session_id,
            )
        )

    @staticmethod
    def create_assistant(
        message_id: str,
        session_id: str,
        model_id: str,
        provider_id: str,
        cwd: str,
        root: str,
        created: int
    ) -> MessageInfo:
        """Create an assistant message.

        Args:
            message_id: Unique message ID
            session_id: Session ID
            model_id: Model ID
            provider_id: Provider ID
            cwd: Current working directory
            root: Project root
            created: Creation timestamp (ms)

        Returns:
            MessageInfo for the assistant message
        """
        return MessageInfo(
            id=message_id,
            role=MessageRole.ASSISTANT,
            parts=[],
            metadata=MessageMetadata(
                time=MessageTime(created=created),
                session_id=session_id,
                assistant=AssistantMetadata(
                    model_id=model_id,
                    provider_id=provider_id,
                    path=PathInfo(cwd=cwd, root=root),
                )
            )
        )

    @staticmethod
    def add_text(message: MessageInfo, text: str) -> None:
        """Add text to a message."""
        # Find existing text part or create new one
        for part in message.parts:
            if isinstance(part, TextPart):
                part.text += text
                return
        message.parts.append(TextPart(text=text))

    @staticmethod
    def add_reasoning(message: MessageInfo, text: str) -> None:
        """Add reasoning to a message."""
        message.parts.append(ReasoningPart(text=text))

    @staticmethod
    def add_tool_call(
        message: MessageInfo,
        tool_call_id: str,
        tool_name: str,
        args: Any,
        step: Optional[int] = None
    ) -> None:
        """Add a tool call to a message."""
        message.parts.append(ToolInvocationPart(
            tool_invocation=ToolCall(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                args=args,
                step=step
            )
        ))

    @staticmethod
    def add_tool_result(
        message: MessageInfo,
        tool_call_id: str,
        tool_name: str,
        args: Any,
        result: str,
        step: Optional[int] = None
    ) -> None:
        """Add a tool result to a message."""
        message.parts.append(ToolInvocationPart(
            tool_invocation=ToolResult(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                args=args,
                result=result,
                step=step
            )
        ))

    @staticmethod
    def add_file(
        message: MessageInfo,
        media_type: str,
        url: str,
        filename: Optional[str] = None,
    ) -> None:
        """Add a file attachment part."""
        message.parts.append(
            FilePart(
                media_type=media_type,
                filename=filename,
                url=url,
            )
        )

    @staticmethod
    def complete(message: MessageInfo, completed: int) -> None:
        """Mark a message as completed."""
        message.metadata.time.completed = completed

    @staticmethod
    def get_text(message: MessageInfo) -> str:
        """Extract all text content from a message."""
        parts = []
        for part in message.parts:
            if isinstance(part, TextPart):
                parts.append(part.text)
        return "".join(parts)
