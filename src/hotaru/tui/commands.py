"""Command system for TUI.

This module provides a command palette system for the TUI,
allowing users to execute commands via keyboard shortcuts or search.
"""

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional
from enum import Enum


class CommandCategory(str, Enum):
    """Command categories for organization."""
    SESSION = "Session"
    AGENT = "Agent"
    PROVIDER = "Provider"
    SYSTEM = "System"
    NAVIGATION = "Navigation"


@dataclass
class Command:
    """Command definition.

    Attributes:
        id: Unique command identifier
        title: Display title
        category: Command category
        keybind: Optional keyboard shortcut
        on_select: Callback when command is selected
        enabled: Whether command is currently enabled
        hidden: Whether to hide from command palette
        suggested: Whether to suggest this command
        slash_name: Slash command name (e.g., "/new")
        slash_aliases: Alternative slash command names
    """
    id: str
    title: str
    category: CommandCategory = CommandCategory.SYSTEM
    keybind: Optional[str] = None
    on_select: Optional[Callable[..., None]] = None
    enabled: bool = True
    availability_reason: Optional[str] = None
    hidden: bool = False
    suggested: bool = False
    slash_name: Optional[str] = None
    slash_aliases: List[str] = field(default_factory=list)


class CommandRegistry:
    """Registry for TUI commands.

    Manages command registration, lookup, and execution.
    """

    def __init__(self):
        self._commands: Dict[str, Command] = {}
        self._keybinds: Dict[str, str] = {}  # keybind -> command_id
        self._slash_commands: Dict[str, str] = {}  # slash_name -> command_id

    def register(self, command: Command) -> None:
        """Register a command.

        Args:
            command: Command to register
        """
        self._commands[command.id] = command

        if command.keybind:
            self._keybinds[command.keybind] = command.id

        if command.slash_name:
            self._slash_commands[command.slash_name] = command.id
            for alias in command.slash_aliases:
                self._slash_commands[alias] = command.id

    def unregister(self, command_id: str) -> None:
        """Unregister a command.

        Args:
            command_id: ID of command to unregister
        """
        if command_id in self._commands:
            command = self._commands[command_id]

            if command.keybind and command.keybind in self._keybinds:
                del self._keybinds[command.keybind]

            if command.slash_name:
                if command.slash_name in self._slash_commands:
                    del self._slash_commands[command.slash_name]
                for alias in command.slash_aliases:
                    if alias in self._slash_commands:
                        del self._slash_commands[alias]

            del self._commands[command_id]

    def get(self, command_id: str) -> Optional[Command]:
        """Get a command by ID.

        Args:
            command_id: Command ID

        Returns:
            Command if found, None otherwise
        """
        return self._commands.get(command_id)

    def get_by_keybind(self, keybind: str) -> Optional[Command]:
        """Get a command by keyboard shortcut.

        Args:
            keybind: Keyboard shortcut string

        Returns:
            Command if found, None otherwise
        """
        command_id = self._keybinds.get(keybind)
        if command_id:
            return self._commands.get(command_id)
        return None

    def get_by_slash(self, slash_name: str) -> Optional[Command]:
        """Get a command by slash command name.

        Args:
            slash_name: Slash command name (without leading /)

        Returns:
            Command if found, None otherwise
        """
        command_id = self._slash_commands.get(slash_name)
        if command_id:
            return self._commands.get(command_id)
        return None

    def execute(
        self,
        command_id: str,
        source: str = "palette",
        argument: Optional[str] = None,
    ) -> tuple[bool, Optional[str]]:
        """Execute a command by ID.

        Args:
            command_id: Command ID to execute
            source: Invocation source (palette, keybind, slash)
            argument: Optional command argument text

        Returns:
            Tuple of (executed, unavailable reason)
        """
        command = self._commands.get(command_id)
        if not command:
            return False, None

        if not command.enabled:
            return False, command.availability_reason

        if not command.on_select:
            return False, "Command is not wired yet."

        try:
            command.on_select(source=source, argument=argument)
        except TypeError:
            try:
                command.on_select(source, argument)
            except TypeError:
                try:
                    command.on_select(source)
                except TypeError:
                    command.on_select()
        return True, None

    def list_commands(
        self,
        category: Optional[CommandCategory] = None,
        include_hidden: bool = False
    ) -> List[Command]:
        """List all registered commands.

        Args:
            category: Filter by category
            include_hidden: Include hidden commands

        Returns:
            List of commands
        """
        commands = list(self._commands.values())

        if category:
            commands = [c for c in commands if c.category == category]

        if not include_hidden:
            commands = [c for c in commands if not c.hidden]

        return commands

    def search(self, query: str) -> List[Command]:
        """Search commands by title.

        Args:
            query: Search query

        Returns:
            List of matching commands
        """
        query = query.lower()
        results = []

        for command in self._commands.values():
            if command.hidden:
                continue

            # Check title match
            if query in command.title.lower():
                results.append(command)
                continue

            # Check slash command match
            if command.slash_name and query in command.slash_name.lower():
                results.append(command)
                continue

            # Check aliases
            for alias in command.slash_aliases:
                if query in alias.lower():
                    results.append(command)
                    break

        # Sort by suggested first, then by title
        results.sort(key=lambda c: (not c.suggested, c.title.lower()))

        return results


# Default commands for the TUI
def create_default_commands() -> List[Command]:
    """Create the default set of TUI commands.

    Returns:
        List of default commands
    """
    return [
        # Session commands
        Command(
            id="session.list",
            title="Switch session",
            category=CommandCategory.SESSION,
            keybind="ctrl+s",
            slash_name="sessions",
            slash_aliases=["resume", "continue"],
            suggested=True,
        ),
        Command(
            id="session.new",
            title="New session",
            category=CommandCategory.SESSION,
            keybind="ctrl+n",
            slash_name="new",
            slash_aliases=["clear"],
        ),
        Command(
            id="project.init",
            title="Initialize AGENTS.md",
            category=CommandCategory.SESSION,
            slash_name="init",
            suggested=True,
        ),
        Command(
            id="session.share",
            title="Share session",
            category=CommandCategory.SESSION,
            slash_name="share",
        ),
        Command(
            id="session.undo",
            title="Undo previous turn",
            category=CommandCategory.SESSION,
            keybind="ctrl+z",
            slash_name="undo",
        ),
        Command(
            id="session.redo",
            title="Redo undone turn",
            category=CommandCategory.SESSION,
            keybind="ctrl+y",
            slash_name="redo",
        ),
        Command(
            id="session.rename",
            title="Rename session",
            category=CommandCategory.SESSION,
            slash_name="rename",
        ),
        Command(
            id="session.compact",
            title="Compact session",
            category=CommandCategory.SESSION,
            slash_name="compact",
            slash_aliases=["summarize"],
        ),
        Command(
            id="session.export",
            title="Export session transcript",
            category=CommandCategory.SESSION,
            slash_name="export",
        ),
        Command(
            id="session.copy",
            title="Copy session transcript",
            category=CommandCategory.SESSION,
            slash_name="copy",
        ),
        Command(
            id="session.toggle.actions",
            title="Toggle tool details",
            category=CommandCategory.SESSION,
            slash_name="actions",
            slash_aliases=["toggle-actions"],
        ),
        Command(
            id="session.toggle.thinking",
            title="Toggle thinking",
            category=CommandCategory.SESSION,
            slash_name="thinking",
            slash_aliases=["toggle-thinking"],
        ),
        Command(
            id="session.toggle.assistant_metadata",
            title="Toggle assistant metadata",
            category=CommandCategory.SESSION,
            slash_name="assistant-metadata",
            slash_aliases=["toggle-assistant-metadata"],
        ),
        Command(
            id="session.toggle.timestamps",
            title="Toggle timestamps",
            category=CommandCategory.SESSION,
            slash_name="timestamps",
            slash_aliases=["toggle-timestamps"],
        ),

        # Agent commands
        Command(
            id="model.list",
            title="Switch model",
            category=CommandCategory.AGENT,
            keybind="ctrl+m",
            slash_name="models",
            suggested=True,
        ),
        Command(
            id="agent.list",
            title="Switch agent",
            category=CommandCategory.AGENT,
            keybind="ctrl+a",
            slash_name="agents",
        ),
        Command(
            id="mcp.list",
            title="Toggle MCPs",
            category=CommandCategory.AGENT,
            slash_name="mcps",
        ),
        Command(
            id="mcp.auth",
            title="Authenticate MCP",
            category=CommandCategory.AGENT,
            slash_name="mcp-auth",
        ),
        Command(
            id="mcp.logout",
            title="Logout MCP OAuth",
            category=CommandCategory.AGENT,
            slash_name="mcp-logout",
        ),
        Command(
            id="mcp.connect",
            title="Connect MCP",
            category=CommandCategory.AGENT,
            slash_name="mcp-connect",
        ),
        Command(
            id="mcp.disconnect",
            title="Disconnect MCP",
            category=CommandCategory.AGENT,
            slash_name="mcp-disconnect",
        ),

        # Provider commands
        Command(
            id="provider.connect",
            title="Connect provider",
            category=CommandCategory.PROVIDER,
            slash_name="connect",
        ),

        # System commands
        Command(
            id="status.view",
            title="View status",
            category=CommandCategory.SYSTEM,
            slash_name="status",
        ),
        Command(
            id="theme.switch",
            title="Switch theme",
            category=CommandCategory.SYSTEM,
            slash_name="themes",
        ),
        Command(
            id="theme.toggle_mode",
            title="Toggle appearance",
            category=CommandCategory.SYSTEM,
        ),
        Command(
            id="help.show",
            title="Help",
            category=CommandCategory.SYSTEM,
            keybind="f1",
            slash_name="help",
        ),
        Command(
            id="app.exit",
            title="Exit the app",
            category=CommandCategory.SYSTEM,
            keybind="ctrl+c",
            slash_name="exit",
            slash_aliases=["quit", "q"],
        ),

        # Navigation commands (hidden from palette)
        Command(
            id="messages.page_up",
            title="Page up",
            category=CommandCategory.NAVIGATION,
            keybind="pageup",
            hidden=True,
        ),
        Command(
            id="messages.page_down",
            title="Page down",
            category=CommandCategory.NAVIGATION,
            keybind="pagedown",
            hidden=True,
        ),
        Command(
            id="messages.first",
            title="First message",
            category=CommandCategory.NAVIGATION,
            keybind="home",
            hidden=True,
        ),
        Command(
            id="messages.last",
            title="Last message",
            category=CommandCategory.NAVIGATION,
            keybind="end",
            hidden=True,
        ),
    ]
