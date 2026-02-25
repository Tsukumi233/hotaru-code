"""Input widgets: PromptInput, SlashCommandItem, SlashPopover."""

import re
from dataclasses import dataclass
from typing import List, Optional

from textual import events
from textual.app import ComposeResult
from textual.containers import ScrollableContainer
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static, TextArea
from rich.text import Text

from ..theme import ThemeManager
from ..util import FilteredList


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


class PromptInput(TextArea):
    """Custom input widget for the prompt.

    Supports multi-line input, special key bindings, and slash command completion.
    """

    MAX_LINES = 8

    DEFAULT_CSS = f"""
    PromptInput {{
        width: 100%;
        height: auto;
        min-height: 3;
        max-height: {MAX_LINES + 2};
        overflow-y: auto;
    }}
    """

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
        super().__init__(placeholder=placeholder, show_line_numbers=False, highlight_cursor_line=False, **kwargs)
        self._commands = commands or []
        self._popover_visible = False
        self._filtered_list: Optional[FilteredList["SlashCommandItem"]] = None
        self._popover: Optional["SlashPopover"] = None

    @property
    def value(self) -> str:
        """Backward-compatible alias for input text."""
        return self.text

    @value.setter
    def value(self, value: str) -> None:
        self.load_text(value)
        self.cursor_position = len(value)

    @property
    def cursor_position(self) -> int:
        """Backward-compatible alias for cursor offset."""
        return self._offset_from_location(self.cursor_location)

    @cursor_position.setter
    def cursor_position(self, value: int) -> None:
        self.cursor_location = self._location_from_offset(value)

    def set_commands(self, commands: List["SlashCommandItem"]) -> None:
        """Set available slash commands."""
        self._commands = commands
        if self._filtered_list:
            self._filtered_list.items = commands

    def on_mount(self) -> None:
        """Handle mount event."""
        self._filtered_list = FilteredList(
            items=self._commands,
            key=lambda x: x.id,
            filter_keys=["trigger", "title", "description"],
        )

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Watch for text changes to detect slash commands."""
        if event.text_area is not self:
            return
        if not self.is_mounted:
            return
        query = self._slash_query(self.value)
        if query is None:
            self._hide_popover()
            return
        self._show_popover(query)

    @staticmethod
    def _slash_query(value: str) -> Optional[str]:
        """Return slash query for single-line slash command values."""
        match = re.fullmatch(r"/(\S*)", value)
        if not match:
            return None
        return match.group(1)

    def _location_from_offset(self, value: int) -> tuple[int, int]:
        text = self.text
        pos = max(0, min(int(value), len(text)))
        head = text[:pos]
        row = head.count("\n")
        if row == 0:
            return (0, pos)
        return (row, pos - head.rfind("\n") - 1)

    def _offset_from_location(self, value: tuple[int, int]) -> int:
        lines = self.text.split("\n")
        row = max(0, min(int(value[0]), len(lines) - 1))
        col = max(0, min(int(value[1]), len(lines[row])))
        if row == 0:
            return col
        return sum(len(line) + 1 for line in lines[:row]) + col

    def _show_popover(self, query: str) -> None:
        """Show slash command popover."""
        if not self._filtered_list:
            return
        self._filtered_list.set_filter(query)
        if not self._popover_visible:
            self._popover_visible = True
            self._popover = SlashPopover(
                items=self._filtered_list.filtered,
                active_index=self._filtered_list.active_index,
            )
            self.screen.mount(self._popover)
            self.call_after_refresh(self._update_popover_position)
        else:
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
        """Select a slash command."""
        self._hide_popover()
        if item.type == "custom":
            self.value = f"/{item.trigger} "
            self.cursor_position = len(self.value)
        else:
            self.value = ""
            self.post_message(self.SlashCommandSelected(item.id, item.trigger))

    def action_submit(self) -> None:
        """Handle submit action."""
        if self._popover_visible and self._filtered_list:
            item = self._filtered_list.active
            if item:
                self._select_command(item)
                return
        if self.value.strip():
            self.post_message(self.Submitted(self.value))
            self.value = ""

    def on_key(self, event: events.Key) -> None:
        """Handle key events for popover navigation."""
        if event.key == "shift+enter":
            self.insert("\n")
            event.prevent_default()
            event.stop()
            return
        if event.key == "enter":
            if self._popover_visible:
                self.action_popover_select()
            else:
                self.action_submit()
            event.prevent_default()
            event.stop()
            return
        if not self._popover_visible:
            return
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
        """Update the items list."""
        self._items = items
        self._active_index = active_index
        self._render_items()

    def set_active(self, index: int) -> None:
        """Set the active item index."""
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
        self._scroll_to_active()

    def _create_item_widget(self, item: SlashCommandItem, is_active: bool) -> Static:
        """Create a widget for a slash command item."""
        theme = ThemeManager.get_theme()
        text = Text()
        text.append(f"/{item.trigger}", style=f"bold {theme.accent}")
        text.append(" ")
        text.append(item.title, style=theme.text)
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
