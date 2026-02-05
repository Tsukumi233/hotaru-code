"""Terminal User Interface (TUI) for Hotaru Code.

This module provides a rich terminal interface for interacting with
the AI coding assistant. Built on Textual for cross-platform support.

Features:
- Session management with message history
- Real-time streaming of AI responses
- Tool execution visualization
- Syntax-highlighted code display
- Keyboard shortcuts and commands
- Theme support (dark/light)

Example:
    from hotaru.tui import TuiApp, run_tui

    # Run the TUI application
    run_tui()

    # Or with options
    run_tui(
        model="anthropic/claude-3-opus",
        agent="build",
        continue_session=True
    )
"""

from .app import TuiApp, run_tui
from .event import TuiEvent
from .theme import Theme, ThemeManager, THEMES
from .commands import Command, CommandRegistry, CommandCategory
from .widgets import (
    Logo,
    PromptInput,
    MessageBubble,
    ToolDisplay,
    CodeBlock,
    DiffDisplay,
    Toast,
    Spinner,
    StatusBar,
    SlashCommandItem,
    SlashPopover,
)
from .dialogs import (
    ConfirmDialog,
    AlertDialog,
    InputDialog,
    SelectDialog,
    ModelSelectDialog,
    SessionListDialog,
    HelpDialog,
)
from .screens import HomeScreen, SessionScreen

# Context providers
from .context import (
    RouteContext,
    RouteProvider,
    Route,
    HomeRoute,
    SessionRoute,
    LocalContext,
    LocalProvider,
    SyncContext,
    SyncProvider,
    ArgsContext,
    ArgsProvider,
    Args,
    KVContext,
    KVProvider,
    SDKContext,
    SDKProvider,
)

__all__ = [
    # Main app
    "TuiApp",
    "run_tui",
    # Events
    "TuiEvent",
    # Theme
    "Theme",
    "ThemeManager",
    "THEMES",
    # Commands
    "Command",
    "CommandRegistry",
    "CommandCategory",
    # Widgets
    "Logo",
    "PromptInput",
    "MessageBubble",
    "ToolDisplay",
    "CodeBlock",
    "DiffDisplay",
    "Toast",
    "Spinner",
    "StatusBar",
    "SlashCommandItem",
    "SlashPopover",
    # Dialogs
    "ConfirmDialog",
    "AlertDialog",
    "InputDialog",
    "SelectDialog",
    "ModelSelectDialog",
    "SessionListDialog",
    "HelpDialog",
    # Screens
    "HomeScreen",
    "SessionScreen",
    # Context - Route
    "RouteContext",
    "RouteProvider",
    "Route",
    "HomeRoute",
    "SessionRoute",
    # Context - Local
    "LocalContext",
    "LocalProvider",
    # Context - Sync
    "SyncContext",
    "SyncProvider",
    # Context - Args
    "ArgsContext",
    "ArgsProvider",
    "Args",
    # Context - KV
    "KVContext",
    "KVProvider",
    # Context - SDK
    "SDKContext",
    "SDKProvider",
]
