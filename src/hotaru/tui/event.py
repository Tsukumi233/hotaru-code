"""TUI event definitions.

This module defines events used for communication between TUI components
and the rest of the application.
"""

from pydantic import BaseModel
from typing import Literal, Optional

from ..core.bus import BusEvent


class PromptAppendProps(BaseModel):
    """Properties for prompt append event."""
    text: str


class CommandExecuteProps(BaseModel):
    """Properties for command execute event."""
    command: str


class ToastShowProps(BaseModel):
    """Properties for toast show event.

    Attributes:
        title: Optional toast title
        message: Toast message content
        variant: Toast style variant
        duration: Display duration in milliseconds
    """
    title: Optional[str] = None
    message: str
    variant: Literal["info", "success", "warning", "error"]
    duration: int = 5000


class SessionSelectProps(BaseModel):
    """Properties for session select event."""
    session_id: str


class TuiEvent:
    """TUI event definitions.

    These events are used for communication between TUI components
    and can be published/subscribed via the Bus system.
    """

    # Append text to the prompt input
    PromptAppend = BusEvent.define("tui.prompt.append", PromptAppendProps)

    # Execute a command by name
    CommandExecute = BusEvent.define("tui.command.execute", CommandExecuteProps)

    # Show a toast notification
    ToastShow = BusEvent.define("tui.toast.show", ToastShowProps)

    # Navigate to a specific session
    SessionSelect = BusEvent.define("tui.session.select", SessionSelectProps)
