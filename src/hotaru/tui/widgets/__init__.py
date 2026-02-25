"""TUI widgets for Hotaru Code.

This package provides custom Textual widgets used in the TUI,
including message displays, tool visualizations, and input components.
"""

from .common import Logo, Spinner, Toast
from .display import CodeBlock, DiffDisplay, ToolDisplay
from .input import PromptInput, SlashCommandItem, SlashPopover
from .layout import (
    AppFooter,
    PromptHints,
    PromptMeta,
    SessionHeaderBar,
    SessionListItem,
)
from .message import AssistantTextPart, MessageBubble

__all__ = [
    "AppFooter",
    "AssistantTextPart",
    "CodeBlock",
    "DiffDisplay",
    "Logo",
    "MessageBubble",
    "PromptHints",
    "PromptInput",
    "PromptMeta",
    "SessionHeaderBar",
    "SessionListItem",
    "SlashCommandItem",
    "SlashPopover",
    "Spinner",
    "Toast",
    "ToolDisplay",
]
