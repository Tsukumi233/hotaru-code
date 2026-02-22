"""Types shared by session processor and collaborators."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ToolCallState:
    """State of a tool call in progress."""

    id: str
    name: str
    input_json: str = ""
    input: Dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    output: Optional[str] = None
    error: Optional[str] = None
    title: Optional[str] = None
    attachments: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    start_time: Optional[int] = None
    end_time: Optional[int] = None


@dataclass
class ProcessorResult:
    """Result of processing a message."""

    status: str
    text: str = ""
    tool_calls: List[ToolCallState] = field(default_factory=list)
    error: Optional[str] = None
    usage: Dict[str, int] = field(default_factory=dict)
    stop_reason: Optional[str] = None
    structured_output: Optional[Any] = None
    reasoning_text: str = ""
