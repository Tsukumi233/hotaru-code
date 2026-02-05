"""TUI widgets for Hotaru Code.

This module provides custom Textual widgets used in the TUI,
including message displays, tool visualizations, and input components.
"""

import re
from dataclasses import dataclass
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import Static, Input, Button, Label, ListView, ListItem, OptionList
from textual.widgets.option_list import Option
from textual.widget import Widget
from textual.reactive import reactive
from textual.message import Message
from textual.binding import Binding
from rich.text import Text
from rich.panel import Panel
from rich.syntax import Syntax
from rich.markdown import Markdown
from rich.console import Group
from typing import Any, Dict, List, Optional, Callable

from .theme import ThemeManager
from .util import FilteredList, fuzzy_match


class Logo(Static):
    """Hotaru Code logo widget."""

    LOGO = """
 ██╗  ██╗ ██████╗ ████████╗ █████╗ ██████╗ ██╗   ██╗
 ██║  ██║██╔═══██╗╚══██╔══╝██╔══██╗██╔══██╗██║   ██║
 ███████║██║   ██║   ██║   ███████║██████╔╝██║   ██║
 ██╔══██║██║   ██║   ██║   ██╔══██║██╔══██╗██║   ██║
 ██║  ██║╚██████╔╝   ██║   ██║  ██║██║  ██║╚██████╔╝
 ╚═╝  ╚═╝ ╚═════╝    ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝
    """

    def render(self) -> Text:
        """Render the logo."""
        theme = ThemeManager.get_theme()
        return Text(self.LOGO.strip(), style=f"bold {theme.accent}")


class PromptInput(Input):
    """Custom input widget for the prompt.

    Supports multi-line input, special key bindings, and slash command completion.
    """

    BINDINGS = [
        Binding("up", "popover_up", "Up", show=False),
        Binding("down", "popover_down", "Down", show=False),
        Binding("tab", "popover_select", "Select", show=False),
        Binding("escape", "popover_close", "Close", show=False),
    ]

    class Submitted(Message):
        """Message sent when prompt is submitted."""

        def __init__(self, value: str) -> None:
            self.value = value
            super().__init__()

    class SlashCommandSelected(Message):
        """Message sent when a slash command is selected."""

        def __init__(self, command_id: str, trigger: str) -> None:
            self.command_id = command_id
            self.trigger = trigger
            super().__init__()

    def __init__(
        self,
        placeholder: str = "Type your message...",
        commands: Optional[List["SlashCommandItem"]] = None,
        **kwargs
    ) -> None:
        super().__init__(placeholder=placeholder, **kwargs)
        self._commands = commands or []
        self._popover_visible = False
        self._filtered_list: Optional[FilteredList["SlashCommandItem"]] = None
        self._popover: Optional["SlashPopover"] = None

    def set_commands(self, commands: List["SlashCommandItem"]) -> None:
        """Set available slash commands.

        Args:
            commands: List of slash command items
        """
        self._commands = commands
        if self._filtered_list:
            self._filtered_list.items = commands

    def on_mount(self) -> None:
        """Handle mount event."""
        # Initialize filtered list
        self._filtered_list = FilteredList(
            items=self._commands,
            key=lambda x: x.id,
            filter_keys=["trigger", "title", "description"],
        )

    def watch_value(self, value: str) -> None:
        """Watch for value changes to detect slash commands."""
        # Check for slash command pattern at start
        match = re.match(r"^/(\S*)$", value)
        if match:
            query = match.group(1)
            self._show_popover(query)
        else:
            self._hide_popover()

    def _show_popover(self, query: str) -> None:
        """Show slash command popover.

        Args:
            query: Filter query (text after /)
        """
        if not self._filtered_list:
            return

        self._filtered_list.set_filter(query)

        if not self._popover_visible:
            self._popover_visible = True
            # Create and mount popover
            self._popover = SlashPopover(
                items=self._filtered_list.filtered,
                active_index=self._filtered_list.active_index,
            )
            # Mount above the input
            self.screen.mount(self._popover)
            self._update_popover_position()
        else:
            # Update existing popover
            if self._popover:
                self._popover.update_items(
                    self._filtered_list.filtered,
                    self._filtered_list.active_index,
                )

    def _hide_popover(self) -> None:
        """Hide slash command popover."""
        if self._popover_visible and self._popover:
            self._popover_visible = False
            self._popover.remove()
            self._popover = None

    def _update_popover_position(self) -> None:
        """Update popover position relative to input."""
        if self._popover:
            # Position above the input
            region = self.region
            self._popover.styles.offset = (region.x, region.y - self._popover.size.height - 1)

    def action_popover_up(self) -> None:
        """Move selection up in popover."""
        if self._popover_visible and self._filtered_list:
            self._filtered_list.move_up()
            if self._popover:
                self._popover.set_active(self._filtered_list.active_index)

    def action_popover_down(self) -> None:
        """Move selection down in popover."""
        if self._popover_visible and self._filtered_list:
            self._filtered_list.move_down()
            if self._popover:
                self._popover.set_active(self._filtered_list.active_index)

    def action_popover_select(self) -> None:
        """Select current item in popover."""
        if self._popover_visible and self._filtered_list:
            item = self._filtered_list.active
            if item:
                self._select_command(item)

    def action_popover_close(self) -> None:
        """Close popover."""
        if self._popover_visible:
            self._hide_popover()
            self.value = ""

    def _select_command(self, item: "SlashCommandItem") -> None:
        """Select a slash command.

        Args:
            item: Selected command item
        """
        self._hide_popover()

        if item.type == "custom":
            # For custom commands, insert the trigger
            self.value = f"/{item.trigger} "
            self.cursor_position = len(self.value)
        else:
            # For builtin commands, clear input and trigger command
            self.value = ""
            self.post_message(self.SlashCommandSelected(item.id, item.trigger))

    def action_submit(self) -> None:
        """Handle submit action."""
        # If popover is visible, select the active item
        if self._popover_visible and self._filtered_list:
            item = self._filtered_list.active
            if item:
                self._select_command(item)
                return

        # Otherwise submit the message
        if self.value.strip():
            self.post_message(self.Submitted(self.value))
            self.value = ""

    def on_key(self, event) -> None:
        """Handle key events for popover navigation."""
        if not self._popover_visible:
            return

        # Handle navigation keys
        if event.key == "up":
            self.action_popover_up()
            event.prevent_default()
            event.stop()
        elif event.key == "down":
            self.action_popover_down()
            event.prevent_default()
            event.stop()
        elif event.key == "tab":
            self.action_popover_select()
            event.prevent_default()
            event.stop()
        elif event.key == "escape":
            self.action_popover_close()
            event.prevent_default()
            event.stop()
        elif event.key == "enter":
            self.action_popover_select()
            event.prevent_default()
            event.stop()


@dataclass
class SlashCommandItem:
    """Slash command item for autocomplete."""
    id: str
    trigger: str
    title: str
    description: str = ""
    keybind: Optional[str] = None
    type: str = "builtin"  # "builtin" or "custom"
    source: Optional[str] = None  # "command", "mcp", "skill"


class SlashPopover(Widget):
    """Popover widget for slash command suggestions.

    Displays a list of matching slash commands with fuzzy filtering.
    """

    DEFAULT_CSS = """
    SlashPopover {
        layer: overlay;
        width: auto;
        min-width: 40;
        max-width: 60;
        height: auto;
        max-height: 12;
        background: $surface;
        border: solid $primary;
        padding: 0;
    }

    SlashPopover .slash-item {
        padding: 0 1;
        height: 2;
    }

    SlashPopover .slash-item.active {
        background: $accent 30%;
    }

    SlashPopover .slash-trigger {
        color: $accent;
    }

    SlashPopover .slash-title {
        color: $text;
    }

    SlashPopover .slash-description {
        color: $text-muted;
    }

    SlashPopover .slash-keybind {
        color: $text-muted;
    }

    SlashPopover .slash-type {
        color: $text-muted;
    }

    SlashPopover .empty-message {
        padding: 1;
        color: $text-muted;
        text-align: center;
    }
    """

    def __init__(
        self,
        items: List[SlashCommandItem],
        active_index: int = 0,
        **kwargs
    ) -> None:
        """Initialize slash popover.

        Args:
            items: List of slash command items
            active_index: Initially active item index
        """
        super().__init__(**kwargs)
        self._items = items
        self._active_index = active_index

    def compose(self) -> ComposeResult:
        """Compose the popover content."""
        yield ScrollableContainer(id="slash-list")

    def on_mount(self) -> None:
        """Handle mount event."""
        self._render_items()

    def update_items(self, items: List[SlashCommandItem], active_index: int) -> None:
        """Update the items list.

        Args:
            items: New list of items
            active_index: New active index
        """
        self._items = items
        self._active_index = active_index
        self._render_items()

    def set_active(self, index: int) -> None:
        """Set the active item index.

        Args:
            index: New active index
        """
        self._active_index = index
        self._update_active_highlight()

    def _render_items(self) -> None:
        """Render the items list."""
        container = self.query_one("#slash-list", ScrollableContainer)
        container.remove_children()

        if not self._items:
            container.mount(Static("No matching commands", classes="empty-message"))
            return

        for i, item in enumerate(self._items):
            is_active = i == self._active_index
            widget = self._create_item_widget(item, is_active)
            widget.set_class(is_active, "active")
            container.mount(widget)

        # Scroll active item into view
        self._scroll_to_active()

    def _create_item_widget(self, item: SlashCommandItem, is_active: bool) -> Static:
        """Create a widget for a slash command item.

        Args:
            item: Slash command item
            is_active: Whether this item is active

        Returns:
            Static widget for the item
        """
        theme = ThemeManager.get_theme()

        text = Text()
        # Trigger
        text.append(f"/{item.trigger}", style=f"bold {theme.accent}")
        text.append(" ")
        # Title
        text.append(item.title, style=theme.text)

        # Second line: description and keybind
        if item.description or item.keybind:
            text.append("\n")
            if item.description:
                desc = item.description[:40] + "..." if len(item.description) > 40 else item.description
                text.append(f"  {desc}", style=theme.text_muted)
            if item.keybind:
                text.append(f" [{item.keybind}]", style=theme.text_muted)

        widget = Static(text, classes="slash-item")
        widget.data_slash_id = item.id
        return widget

    def _update_active_highlight(self) -> None:
        """Update the active highlight on items."""
        container = self.query_one("#slash-list", ScrollableContainer)
        items = list(container.query(".slash-item"))

        for i, widget in enumerate(items):
            widget.set_class(i == self._active_index, "active")

        self._scroll_to_active()

    def _scroll_to_active(self) -> None:
        """Scroll the active item into view."""
        container = self.query_one("#slash-list", ScrollableContainer)
        items = list(container.query(".slash-item"))

        if 0 <= self._active_index < len(items):
            items[self._active_index].scroll_visible()


class MessageBubble(Static):
    """Widget for displaying a chat message.

    Supports both user and assistant messages with different styling.
    """

    def __init__(
        self,
        content: str,
        role: str = "user",
        agent: Optional[str] = None,
        timestamp: Optional[str] = None,
        **kwargs
    ) -> None:
        """Initialize message bubble.

        Args:
            content: Message content
            role: Message role ("user" or "assistant")
            agent: Agent name for assistant messages
            timestamp: Optional timestamp string
        """
        super().__init__(**kwargs)
        self.content = content
        self.role = role
        self.agent = agent
        self.timestamp = timestamp

    def render(self) -> Panel:
        """Render the message bubble."""
        theme = ThemeManager.get_theme()

        if self.role == "user":
            border_color = theme.accent
            title = "You"
        else:
            border_color = theme.primary
            title = self.agent or "Assistant"

        # Render content as markdown for assistant messages
        if self.role == "assistant":
            content = Markdown(self.content)
        else:
            content = Text(self.content)

        return Panel(
            content,
            title=title,
            title_align="left",
            border_style=border_color,
            padding=(0, 1),
        )


class ToolDisplay(Static):
    """Widget for displaying tool execution.

    Shows tool name, status, and output in a collapsible format.
    """

    def __init__(
        self,
        tool_name: str,
        status: str = "pending",
        input_data: Optional[Dict[str, Any]] = None,
        output: Optional[str] = None,
        error: Optional[str] = None,
        **kwargs
    ) -> None:
        """Initialize tool display.

        Args:
            tool_name: Name of the tool
            status: Execution status
            input_data: Tool input parameters
            output: Tool output
            error: Error message if failed
        """
        super().__init__(**kwargs)
        self.tool_name = tool_name
        self.status = status
        self.input_data = input_data or {}
        self.output = output
        self.error = error

    def render(self) -> Text:
        """Render the tool display."""
        theme = ThemeManager.get_theme()

        # Status icon
        if self.status == "completed":
            icon = "✓"
            color = theme.success
        elif self.status == "error":
            icon = "✗"
            color = theme.error
        elif self.status == "running":
            icon = "⟳"
            color = theme.warning
        else:
            icon = "○"
            color = theme.text_muted

        # Build display text
        text = Text()
        text.append(f"{icon} ", style=color)
        text.append(self.tool_name, style="bold")

        # Add input summary
        if self.input_data:
            summary = self._format_input_summary()
            if summary:
                text.append(f" {summary}", style=theme.text_muted)

        # Add error if present
        if self.error:
            text.append(f"\n  Error: {self.error}", style=theme.error)

        return text

    def _format_input_summary(self) -> str:
        """Format input data as a brief summary."""
        parts = []
        for key, value in self.input_data.items():
            if isinstance(value, str) and len(value) < 50:
                parts.append(f"{key}={value}")
            elif isinstance(value, (int, float, bool)):
                parts.append(f"{key}={value}")

        if parts:
            return f"[{', '.join(parts[:3])}]"
        return ""


class CodeBlock(Static):
    """Widget for displaying syntax-highlighted code."""

    def __init__(
        self,
        code: str,
        language: str = "python",
        line_numbers: bool = True,
        **kwargs
    ) -> None:
        """Initialize code block.

        Args:
            code: Code content
            language: Programming language for syntax highlighting
            line_numbers: Whether to show line numbers
        """
        super().__init__(**kwargs)
        self.code = code
        self.language = language
        self.line_numbers = line_numbers

    def render(self) -> Syntax:
        """Render the code block."""
        theme = ThemeManager.get_theme()
        theme_name = "monokai" if ThemeManager.get_mode() == "dark" else "github-light"

        return Syntax(
            self.code,
            self.language,
            theme=theme_name,
            line_numbers=self.line_numbers,
            word_wrap=True,
        )


class DiffDisplay(Static):
    """Widget for displaying file diffs."""

    def __init__(
        self,
        diff_content: str,
        file_path: Optional[str] = None,
        **kwargs
    ) -> None:
        """Initialize diff display.

        Args:
            diff_content: Unified diff content
            file_path: Path to the file being diffed
        """
        super().__init__(**kwargs)
        self.diff_content = diff_content
        self.file_path = file_path

    def render(self) -> Text:
        """Render the diff display."""
        theme = ThemeManager.get_theme()
        text = Text()

        for line in self.diff_content.split("\n"):
            if line.startswith("+") and not line.startswith("+++"):
                text.append(line + "\n", style=f"on {theme.diff_added_bg} {theme.diff_added}")
            elif line.startswith("-") and not line.startswith("---"):
                text.append(line + "\n", style=f"on {theme.diff_removed_bg} {theme.diff_removed}")
            elif line.startswith("@@"):
                text.append(line + "\n", style=f"bold {theme.info}")
            else:
                text.append(line + "\n", style=theme.text)

        return text


class Toast(Static):
    """Toast notification widget."""

    DEFAULT_CSS = """
    Toast {
        dock: bottom;
        width: 100%;
        height: auto;
        padding: 1;
        margin: 1;
    }
    """

    def __init__(
        self,
        message: str,
        variant: str = "info",
        title: Optional[str] = None,
        **kwargs
    ) -> None:
        """Initialize toast.

        Args:
            message: Toast message
            variant: Style variant (info, success, warning, error)
            title: Optional title
        """
        super().__init__(**kwargs)
        self.message = message
        self.variant = variant
        self.title = title

    def render(self) -> Panel:
        """Render the toast."""
        theme = ThemeManager.get_theme()

        # Get color based on variant
        colors = {
            "info": theme.info,
            "success": theme.success,
            "warning": theme.warning,
            "error": theme.error,
        }
        color = colors.get(self.variant, theme.info)

        content = Text(self.message)
        title = self.title or self.variant.capitalize()

        return Panel(
            content,
            title=title,
            border_style=color,
            padding=(0, 1),
        )


class Spinner(Static):
    """Animated spinner widget."""

    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    frame_index = reactive(0)

    def __init__(self, text: str = "Loading...", **kwargs) -> None:
        """Initialize spinner.

        Args:
            text: Text to display next to spinner
        """
        super().__init__(**kwargs)
        self.text = text
        self._timer = None

    def on_mount(self) -> None:
        """Start animation when mounted."""
        self._timer = self.set_interval(0.1, self._advance_frame)

    def on_unmount(self) -> None:
        """Stop animation when unmounted."""
        if self._timer:
            self._timer.stop()

    def _advance_frame(self) -> None:
        """Advance to next animation frame."""
        self.frame_index = (self.frame_index + 1) % len(self.FRAMES)

    def render(self) -> Text:
        """Render the spinner."""
        theme = ThemeManager.get_theme()
        frame = self.FRAMES[self.frame_index]
        return Text(f"{frame} {self.text}", style=theme.accent)


class StatusBar(Static):
    """Status bar widget showing current state."""

    def __init__(
        self,
        model: Optional[str] = None,
        agent: Optional[str] = None,
        session_id: Optional[str] = None,
        **kwargs
    ) -> None:
        """Initialize status bar.

        Args:
            model: Current model name
            agent: Current agent name
            session_id: Current session ID
        """
        super().__init__(**kwargs)
        self.model = model
        self.agent = agent
        self.session_id = session_id

    def render(self) -> Text:
        """Render the status bar."""
        theme = ThemeManager.get_theme()
        text = Text()

        if self.agent:
            text.append(f"▣ {self.agent}", style=f"bold {theme.primary}")
            text.append(" · ", style=theme.text_muted)

        if self.model:
            text.append(self.model, style=theme.text_muted)

        if self.session_id:
            text.append(" · ", style=theme.text_muted)
            text.append(self.session_id[:8], style=theme.text_muted)

        return text


class SessionListItem(ListItem):
    """List item for session selection."""

    def __init__(
        self,
        session_id: str,
        title: str,
        updated: str,
        **kwargs
    ) -> None:
        """Initialize session list item.

        Args:
            session_id: Session ID
            title: Session title
            updated: Last updated timestamp
        """
        super().__init__(**kwargs)
        self.session_id = session_id
        self.title = title
        self.updated = updated

    def compose(self) -> ComposeResult:
        """Compose the list item."""
        theme = ThemeManager.get_theme()
        yield Static(
            Text.assemble(
                (self.title, "bold"),
                "\n",
                (self.updated, theme.text_muted),
            )
        )
