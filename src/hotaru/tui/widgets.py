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
            # Defer positioning until after layout
            self.call_after_refresh(self._update_popover_position)
        else:
            # Update existing popover
            if self._popover:
                self._popover.update_items(
                    self._filtered_list.filtered,
                    self._filtered_list.active_index,
                )
                self.call_after_refresh(self._update_popover_position)

    def _hide_popover(self) -> None:
        """Hide slash command popover."""
        if self._popover_visible and self._popover:
            self._popover_visible = False
            self._popover.remove()
            self._popover = None

    def _update_popover_position(self) -> None:
        """Update popover position relative to input."""
        if not self._popover:
            return

        # outer_size includes border; size does not
        popover_h = self._popover.outer_size.height

        if popover_h == 0:
            self.call_after_refresh(self._update_popover_position)
            return

        region = self.region
        y = max(0, region.y - popover_h)
        self._popover.styles.offset = (region.x, y)

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
        position: absolute;
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

    def render(self):
        """Render the message bubble."""
        theme = ThemeManager.get_theme()

        if self.role == "user":
            return Panel(
                Text(self.content),
                title="You",
                title_align="left",
                border_style=theme.accent,
                padding=(0, 1),
            )

        # Assistant messages: render without Panel for clean text selection
        text = Text()
        title = self.agent or "Assistant"
        text.append(f"{title}\n", style=f"bold {theme.primary}")
        if self.content:
            text.append(self.content)
        return text


class AssistantTextPart(Static):
    """Widget for a single text segment of an assistant response.

    Used to render text parts interleaved with tool calls.
    Renders as Markdown; click to copy raw text to clipboard.
    """

    def __init__(self, content: str = "", part_id: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self.content = content
        self.part_id = part_id

    def render(self):
        if self.content:
            return Markdown(self.content)
        return Text("")

    def on_click(self) -> None:
        if self.content:
            self.app.copy_to_clipboard(self.content)
            self.app.notify("Copied to clipboard", timeout=1.5)


class ToolDisplay(Static):
    """Widget for displaying tool execution inline.

    Renders tool-specific icons, descriptions, and status indicators
    following the OpenCode InlineTool/BlockTool pattern.
    """

    # Tool-specific configuration: (icon, pending_text)
    TOOL_CONFIG: Dict[str, tuple] = {
        "bash": ("$", "Running command..."),
        "read": ("\u2192", "Reading file..."),
        "write": ("\u2190", "Writing file..."),
        "edit": ("\u2190", "Editing file..."),
        "glob": ("\u2731", "Finding files..."),
        "grep": ("\u2731", "Searching content..."),
        "skill": ("\u2192", "Loading skill..."),
    }

    MAX_OUTPUT_LINES = 10

    def __init__(
        self,
        tool_name: str,
        tool_id: str = "",
        status: str = "running",
        input_data: Optional[Dict[str, Any]] = None,
        output: Optional[str] = None,
        error: Optional[str] = None,
        title: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> None:
        super().__init__(**kwargs)
        self.tool_name = tool_name
        self.tool_id = tool_id
        self.status = status
        self.input_data = input_data or {}
        self.output = output
        self.error = error
        self.title = title
        self.metadata = metadata or {}

    def render(self) -> Text:
        """Render the tool display."""
        theme = ThemeManager.get_theme()

        if self.status == "error":
            return self._render_error(theme)
        if self.status == "running":
            return self._render_running(theme)
        return self._render_completed(theme)

    def _render_running(self, theme) -> Text:
        """Render a tool in running state."""
        _, pending_text = self.TOOL_CONFIG.get(
            self.tool_name, ("\u2699", f"Running {self.tool_name}...")
        )
        text = Text()
        text.append("~ ", style=theme.text_muted)
        text.append(pending_text, style=theme.text_muted)
        return text

    def _render_error(self, theme) -> Text:
        """Render a tool in error state."""
        text = Text()
        text.append("\u2717 ", style=theme.error)
        text.append(self.tool_name, style=theme.error)
        if self.error:
            text.append(f"\n  {self.error}", style=theme.error)
        return text

    def _render_completed(self, theme) -> Text:
        """Render a completed tool with tool-specific formatting."""
        name = self.tool_name
        text = Text()

        if name == "bash":
            return self._render_bash(theme)
        elif name == "read":
            return self._render_file_tool(theme, "\u2192", "Read")
        elif name == "write":
            return self._render_file_tool(theme, "\u2190", "Write")
        elif name == "edit":
            return self._render_file_tool(theme, "\u2190", "Edit")
        elif name == "glob":
            return self._render_glob(theme)
        elif name == "grep":
            return self._render_grep(theme)
        elif name == "skill":
            return self._render_skill(theme)
        else:
            return self._render_generic(theme)

    def _render_bash(self, theme) -> Text:
        """Render bash tool with command and output block."""
        text = Text()
        description = self.title or self._get_bash_description()
        text.append("$ ", style=theme.text_muted)
        text.append(description, style=theme.text_muted)

        command = self.input_data.get("command", "")
        if command:
            text.append(f"\n  $ {command}", style=theme.text_muted)

        if self.output:
            lines = self.output.splitlines()
            shown = lines[: self.MAX_OUTPUT_LINES]
            for line in shown:
                text.append(f"\n  \u2502 {line}", style=theme.text_muted)
            if len(lines) > self.MAX_OUTPUT_LINES:
                remaining = len(lines) - self.MAX_OUTPUT_LINES
                text.append(
                    f"\n  \u2502 ... {remaining} more lines",
                    style=theme.text_muted,
                )
        return text

    def _get_bash_description(self) -> str:
        """Build a short description for bash from input."""
        cmd = self.input_data.get("command", "")
        if cmd:
            first_line = cmd.split("\n")[0]
            return first_line[:60] + ("..." if len(first_line) > 60 else "")
        return "command"

    def _render_file_tool(self, theme, icon: str, verb: str) -> Text:
        """Render read/write/edit tool."""
        text = Text()
        file_path = self.input_data.get("file_path", self.input_data.get("path", ""))
        text.append(f"{icon} ", style=theme.text_muted)
        text.append(f"{verb} {file_path}", style=theme.text_muted)
        return text

    def _render_glob(self, theme) -> Text:
        """Render glob tool."""
        text = Text()
        pattern = self.input_data.get("pattern", "")
        count = self._count_matches()
        text.append("\u2731 ", style=theme.text_muted)
        label = f'Glob "{pattern}"'
        if count is not None:
            label += f" ({count} matches)"
        text.append(label, style=theme.text_muted)
        return text

    def _render_grep(self, theme) -> Text:
        """Render grep tool."""
        text = Text()
        pattern = self.input_data.get("pattern", "")
        count = self._count_matches()
        text.append("\u2731 ", style=theme.text_muted)
        label = f'Grep "{pattern}"'
        if count is not None:
            label += f" ({count} matches)"
        text.append(label, style=theme.text_muted)
        return text

    def _render_skill(self, theme) -> Text:
        """Render skill tool."""
        text = Text()
        name = self.input_data.get("name", self.input_data.get("skill", ""))
        text.append("\u2192 ", style=theme.text_muted)
        text.append(f"Skill {name}", style=theme.text_muted)
        return text

    def _render_generic(self, theme) -> Text:
        """Render a generic/unknown tool."""
        text = Text()
        text.append("\u2699 ", style=theme.text_muted)
        summary = self._format_input_summary()
        text.append(f"{self.tool_name} {summary}".strip(), style=theme.text_muted)
        return text

    def _count_matches(self) -> Optional[int]:
        """Count matches from output lines."""
        if not self.output:
            return None
        lines = [l for l in self.output.strip().splitlines() if l.strip()]
        return len(lines)

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
