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
from .state.runtime_status import RuntimeStatusSnapshot
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
            body = Text(self.content)
            if self.timestamp:
                body.append("\n")
                body.append(self.timestamp, style=theme.text_muted)
            return Panel(
                body,
                title="You",
                title_align="left",
                border_style=theme.accent,
                padding=(0, 1),
            )

        # Assistant messages: render without Panel for clean text selection
        text = Text()
        title = self.agent or "Assistant"
        text.append(title, style=f"bold {theme.primary}")
        if self.timestamp:
            text.append(f" · {self.timestamp}", style=theme.text_muted)
        text.append("\n")
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

    MAX_OUTPUT_LINES = 10
    MAX_BLOCK_LINES = 40

    def __init__(
        self,
        part: Optional[Dict[str, Any]] = None,
        show_details: bool = True,
        on_open_session: Optional[Callable[[str], None]] = None,
        *,
        tool_name: str = "",
        tool_id: str = "",
        status: str = "running",
        input_data: Optional[Dict[str, Any]] = None,
        output: Optional[str] = None,
        error: Optional[str] = None,
        title: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.show_details = show_details
        self.on_open_session = on_open_session
        if part is None:
            part = {
                "id": tool_id or f"tool-{tool_name}",
                "type": "tool",
                "tool": tool_name or "tool",
                "call_id": tool_id,
                "state": {
                    "status": status,
                    "input": input_data or {},
                    "output": output,
                    "error": error,
                    "title": title,
                    "metadata": metadata or {},
                },
            }
        self.part = part

    def set_part(self, part: Dict[str, Any]) -> None:
        self.part = part

    def render(self) -> Text:
        theme = ThemeManager.get_theme()
        status = self._status()
        if not self.show_details and status == "completed" and not self._error():
            return Text("")

        renderer = {
            "bash": self._render_bash,
            "read": self._render_read,
            "write": self._render_write,
            "edit": self._render_edit,
            "glob": self._render_glob,
            "grep": self._render_grep,
            "list": self._render_list,
            "webfetch": self._render_webfetch,
            "codesearch": self._render_codesearch,
            "websearch": self._render_websearch,
            "task": self._render_task,
            "apply_patch": self._render_apply_patch,
            "todowrite": self._render_todowrite,
            "question": self._render_question,
            "skill": self._render_skill,
        }.get(self._tool_name(), self._render_generic)
        return renderer(theme)

    def on_click(self) -> None:
        if self._tool_name() != "task" or not self.on_open_session:
            return
        metadata = self._metadata()
        session_id = metadata.get("session_id") or metadata.get("sessionId")
        if isinstance(session_id, str) and session_id:
            self.on_open_session(session_id)

    def _tool_name(self) -> str:
        return str(self.part.get("tool") or "tool")

    def _state(self) -> Dict[str, Any]:
        state = self.part.get("state")
        return state if isinstance(state, dict) else {}

    def _status(self) -> str:
        return str(self._state().get("status") or "pending")

    def _input(self) -> Dict[str, Any]:
        value = self._state().get("input")
        return value if isinstance(value, dict) else {}

    def _metadata(self) -> Dict[str, Any]:
        value = self._state().get("metadata")
        return value if isinstance(value, dict) else {}

    def _title(self) -> str:
        title = self._state().get("title")
        return str(title or "")

    def _output(self) -> str:
        value = self._state().get("output")
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        return str(value)

    def _error(self) -> str:
        value = self._state().get("error")
        return str(value or "")

    def _is_running(self) -> bool:
        return self._status() in {"pending", "running"}

    def _inline(self, theme, *, icon: str, pending: str, done: str) -> Text:
        text = Text()
        if self._is_running():
            text.append("~ ", style=theme.text_muted)
            text.append(pending, style=theme.text_muted)
            return text

        text.append(f"{icon} ", style=theme.text_muted)
        text.append(done, style=theme.text_muted)
        error = self._error()
        if error:
            text.append(f"\n{error}", style=theme.error)
        return text

    def _block(self, theme, title: str, lines: List[str], *, show_spinner: bool = False) -> Text:
        text = Text()
        if show_spinner:
            text.append("~ ", style=theme.text_muted)
            text.append(title, style=theme.text_muted)
        else:
            text.append(title, style=theme.text_muted)
        for line in lines[: self.MAX_BLOCK_LINES]:
            text.append(f"\n{line}", style=theme.text_muted)
        if len(lines) > self.MAX_BLOCK_LINES:
            text.append(f"\n... {len(lines) - self.MAX_BLOCK_LINES} more lines", style=theme.text_muted)
        error = self._error()
        if error:
            text.append(f"\n{error}", style=theme.error)
        return text

    @staticmethod
    def _pick(data: Dict[str, Any], *keys: str, default: str = "") -> str:
        for key in keys:
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
        return default

    def _render_bash(self, theme) -> Text:
        input_data = self._input()
        metadata = self._metadata()
        command = self._pick(input_data, "command")
        description = self._title() or self._pick(metadata, "description") or command or "Shell command"
        output = self._pick(metadata, "output") or self._output()
        if output and self.show_details:
            lines = [f"$ {command}"] if command else []
            shown, remaining = self._limit_lines(output, self.MAX_OUTPUT_LINES)
            lines.extend(shown)
            if remaining > 0:
                lines.append(f"... {remaining} more lines")
            return self._block(theme, f"# {description}", lines, show_spinner=self._is_running())
        return self._inline(theme, icon="$", pending="Writing command...", done=command or description)

    def _render_read(self, theme) -> Text:
        input_data = self._input()
        file_path = self._pick(input_data, "file_path", "filePath", "path")
        return self._inline(theme, icon="\u2192", pending="Reading file...", done=f"Read {file_path}".strip())

    def _render_write(self, theme) -> Text:
        input_data = self._input()
        metadata = self._metadata()
        file_path = self._pick(input_data, "file_path", "filePath", "path")
        if self.show_details and isinstance(metadata.get("diagnostics"), dict):
            content = self._pick(input_data, "content")
            lines = content.splitlines() if content else ["Wrote file successfully."]
            return self._block(theme, f"# Wrote {file_path}", lines)
        return self._inline(theme, icon="\u2190", pending="Preparing write...", done=f"Write {file_path}".strip())

    def _render_edit(self, theme) -> Text:
        input_data = self._input()
        metadata = self._metadata()
        file_path = self._pick(input_data, "file_path", "filePath", "path")
        diff = self._pick(metadata, "diff")
        if self.show_details and diff:
            shown, remaining = self._limit_lines(diff, self.MAX_OUTPUT_LINES)
            if remaining > 0:
                shown.append(f"... {remaining} more lines")
            return self._block(theme, f"\u2190 Edit {file_path}", shown)
        return self._inline(theme, icon="\u2190", pending="Preparing edit...", done=f"Edit {file_path}".strip())

    def _render_glob(self, theme) -> Text:
        input_data = self._input()
        metadata = self._metadata()
        pattern = self._pick(input_data, "pattern", default="*")
        count = metadata.get("count")
        suffix = f" ({count} matches)" if isinstance(count, int) else ""
        return self._inline(theme, icon="\u2731", pending="Finding files...", done=f'Glob "{pattern}"{suffix}')

    def _render_grep(self, theme) -> Text:
        input_data = self._input()
        metadata = self._metadata()
        pattern = self._pick(input_data, "pattern", default="")
        matches = metadata.get("matches")
        suffix = f" ({matches} matches)" if isinstance(matches, int) else ""
        return self._inline(theme, icon="\u2731", pending="Searching content...", done=f'Grep "{pattern}"{suffix}')

    def _render_list(self, theme) -> Text:
        input_data = self._input()
        path = self._pick(input_data, "path", default=".")
        return self._inline(theme, icon="\u2192", pending="Listing directory...", done=f"List {path}")

    def _render_webfetch(self, theme) -> Text:
        input_data = self._input()
        url = self._pick(input_data, "url")
        return self._inline(theme, icon="%", pending="Fetching from the web...", done=f"WebFetch {url}".strip())

    def _render_codesearch(self, theme) -> Text:
        input_data = self._input()
        query = self._pick(input_data, "query")
        return self._inline(theme, icon="\u25c7", pending="Searching code...", done=f'Code search "{query}"')

    def _render_websearch(self, theme) -> Text:
        input_data = self._input()
        query = self._pick(input_data, "query")
        return self._inline(theme, icon="\u25c8", pending="Searching web...", done=f'Web search "{query}"')

    def _render_task(self, theme) -> Text:
        input_data = self._input()
        metadata = self._metadata()
        description = self._pick(input_data, "description")
        subagent = self._pick(input_data, "subagent_type", "subagentType", default="subagent")
        if not self.show_details:
            return self._inline(theme, icon="#", pending="Delegating...", done=f"{subagent} Task {description}".strip())

        session_id = self._pick(metadata, "session_id", "sessionId")
        lines = []
        if description:
            lines.append(description)
        if session_id:
            lines.append(f"session: {session_id} (click to open)")
        title = f"# {subagent.capitalize()} Task"
        return self._block(theme, title, lines or ["Delegating..."], show_spinner=self._is_running())

    def _render_apply_patch(self, theme) -> Text:
        metadata = self._metadata()
        files = metadata.get("files")
        if self.show_details and isinstance(files, list) and files:
            lines: List[str] = []
            for item in files[:10]:
                if not isinstance(item, dict):
                    continue
                rel = self._pick(item, "relativePath", "relative_path", "filePath", "file_path")
                change_type = self._pick(item, "type", default="update")
                additions = item.get("additions", 0)
                deletions = item.get("deletions", 0)
                lines.append(f"{change_type}: {rel} (+{additions}/-{deletions})")
            return self._block(theme, "# Patch", lines)
        return self._inline(theme, icon="%", pending="Preparing patch...", done="Patch")

    def _render_todowrite(self, theme) -> Text:
        metadata = self._metadata()
        todos = metadata.get("todos")
        if self.show_details and isinstance(todos, list) and todos:
            lines: List[str] = []
            for item in todos[:15]:
                if not isinstance(item, dict):
                    continue
                status = str(item.get("status") or "pending")
                content = str(item.get("content") or "")
                lines.append(f"[{status}] {content}")
            return self._block(theme, "# Todos", lines)
        return self._inline(theme, icon="\u2699", pending="Updating todos...", done="Updated todos")

    def _render_question(self, theme) -> Text:
        input_data = self._input()
        metadata = self._metadata()
        questions = input_data.get("questions")
        answers = metadata.get("answers")
        if self.show_details and isinstance(questions, list) and isinstance(answers, list):
            lines: List[str] = []
            for idx, question in enumerate(questions):
                if not isinstance(question, dict):
                    continue
                text = str(question.get("question") or "")
                answer = answers[idx] if idx < len(answers) else []
                if isinstance(answer, list):
                    answer_text = ", ".join(str(a) for a in answer) if answer else "(no answer)"
                else:
                    answer_text = str(answer)
                lines.append(text)
                lines.append(f"  -> {answer_text}")
            return self._block(theme, "# Questions", lines)
        count = len(questions) if isinstance(questions, list) else 0
        return self._inline(theme, icon="\u2192", pending="Asking questions...", done=f"Asked {count} question(s)")

    def _render_skill(self, theme) -> Text:
        input_data = self._input()
        name = self._pick(input_data, "name", "skill")
        return self._inline(theme, icon="\u2192", pending="Loading skill...", done=f'Skill "{name}"')

    def _render_generic(self, theme) -> Text:
        summary = self._format_input_summary(self._input())
        return self._inline(theme, icon="\u2699", pending=f"Running {self._tool_name()}...", done=f"{self._tool_name()} {summary}".strip())

    @staticmethod
    def _format_input_summary(input_data: Dict[str, Any]) -> str:
        parts = []
        for key, value in input_data.items():
            if isinstance(value, str) and len(value) < 60:
                parts.append(f"{key}={value}")
            elif isinstance(value, (int, float, bool)):
                parts.append(f"{key}={value}")
        if parts:
            return f"[{', '.join(parts[:3])}]"
        return ""

    @staticmethod
    def _limit_lines(text: str, max_lines: int) -> tuple[List[str], int]:
        lines = text.splitlines()
        shown = lines[:max_lines]
        remaining = max(0, len(lines) - len(shown))
        return shown, remaining


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
    """Legacy status bar widget (kept for compatibility)."""

    def __init__(
        self,
        model: Optional[str] = None,
        agent: Optional[str] = None,
        session_id: Optional[str] = None,
        **kwargs
    ) -> None:
        super().__init__(**kwargs)
        self.model = model
        self.agent = agent
        self.session_id = session_id

    def render(self) -> Text:
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


class AppFooter(Static):
    """Footer bar matching OpenCode layout.

    Shows directory path on the left, MCP/LSP status indicators and
    version on the right.
    """

    DEFAULT_CSS = """
    AppFooter {
        height: 1;
        dock: bottom;
        padding: 0 2;
    }
    """

    def __init__(
        self,
        directory: str = "",
        mcp_connected: int = 0,
        mcp_error: bool = False,
        lsp_count: int = 0,
        permission_count: int = 0,
        version: str = "",
        show_lsp: bool = False,
        show_status_hint: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.directory = directory
        self.mcp_connected = mcp_connected
        self.mcp_error = mcp_error
        self.lsp_count = lsp_count
        self.permission_count = permission_count
        self.version = version
        self.show_lsp = show_lsp
        self.show_status_hint = show_status_hint

    def apply_runtime_snapshot(
        self,
        snapshot: RuntimeStatusSnapshot,
        *,
        show_lsp: Optional[bool] = None,
    ) -> None:
        """Apply a normalized runtime status snapshot and refresh."""
        self.mcp_connected = snapshot.mcp_connected
        self.mcp_error = snapshot.mcp_error
        self.lsp_count = snapshot.lsp_count
        self.permission_count = snapshot.permission_count
        self.show_status_hint = snapshot.show_status_hint
        if show_lsp is not None:
            self.show_lsp = show_lsp
        self.refresh()

    def render(self) -> Text:
        theme = ThemeManager.get_theme()
        text = Text(no_wrap=True, overflow="ellipsis")

        # Left: directory path
        text.append(self.directory, style=theme.text_muted)

        # Build right-side items
        right_parts: List[Text] = []

        if self.permission_count > 0:
            perm = Text()
            perm.append("△", style=theme.warning)
            suffix = "s" if self.permission_count != 1 else ""
            perm.append(f" {self.permission_count} Permission{suffix}", style=theme.text)
            right_parts.append(perm)

        if self.show_lsp:
            lsp = Text()
            dot_color = theme.success if self.lsp_count > 0 else theme.text_muted
            lsp.append("•", style=dot_color)
            lsp.append(f" {self.lsp_count} LSP", style=theme.text)
            right_parts.append(lsp)

        if self.mcp_connected > 0 or self.mcp_error:
            mcp = Text()
            icon_color = theme.error if self.mcp_error else theme.success
            mcp.append("⊙", style=icon_color)
            mcp.append(f" {self.mcp_connected} MCP", style=theme.text)
            right_parts.append(mcp)

        should_show_status_hint = self.show_status_hint or bool(right_parts)
        if should_show_status_hint:
            right_parts.append(Text("/status", style=theme.text_muted))

        if self.version:
            right_parts.append(Text(self.version, style=theme.text_muted))

        if right_parts:
            # Calculate padding to right-align
            right_text = Text("  ").join(right_parts)
            available = self.size.width - len(self.directory) - 4  # padding
            if available > len(right_text):
                text.append(" " * (available - len(right_text)))
            else:
                text.append("  ")
            text.append_text(right_text)

        return text


class SessionHeaderBar(Static):
    """Session header bar matching OpenCode layout.

    Shows session title on the left, token count + cost on the right.
    """

    DEFAULT_CSS = """
    SessionHeaderBar {
        height: auto;
        min-height: 3;
        padding: 1 2;
        background: $surface;
    }
    """

    def __init__(
        self,
        title: str = "Session",
        context_info: str = "",
        cost: str = "",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.title = title
        self.context_info = context_info
        self.cost = cost

    def render(self) -> Text:
        theme = ThemeManager.get_theme()
        text = Text(no_wrap=True, overflow="ellipsis")

        # Left: # Title
        text.append("# ", style=f"bold {theme.text}")
        text.append(self.title, style=f"bold {theme.text}")

        # Right: context info (tokens + cost)
        if self.context_info:
            right = Text()
            right.append(self.context_info, style=theme.text_muted)
            if self.cost:
                right.append(f" ({self.cost})", style=theme.text_muted)

            available = self.size.width - len(self.title) - 6  # "# " + padding
            if available > len(right):
                text.append(" " * (available - len(right)))
            else:
                text.append("  ")
            text.append_text(right)

        return text


class PromptMeta(Static):
    """Agent name + model info displayed below the prompt input.

    Mirrors the OpenCode prompt footer showing:
      AgentName  model-name  provider
    """

    DEFAULT_CSS = """
    PromptMeta {
        height: 1;
        padding: 0 2;
    }
    """

    def __init__(
        self,
        agent: str = "",
        model: str = "",
        provider: str = "",
        agent_color: str = "",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.agent = agent
        self.model_name = model
        self.provider = provider
        self.agent_color = agent_color

    def render(self) -> Text:
        theme = ThemeManager.get_theme()
        text = Text()
        color = self.agent_color or theme.accent
        if self.agent:
            text.append(self.agent.capitalize(), style=f"bold {color}")
        if self.model_name:
            text.append("  ", style=theme.text_muted)
            text.append(self.model_name, style=theme.text)
        if self.provider:
            text.append("  ", style=theme.text_muted)
            text.append(self.provider, style=theme.text_muted)
        return text


class PromptHints(Static):
    """Keyboard hint bar displayed below the prompt meta line.

    Shows hints like: tab agents  ctrl+p commands
    """

    DEFAULT_CSS = """
    PromptHints {
        height: 1;
        padding: 0 2;
    }
    """

    def __init__(self, hints: Optional[List[tuple]] = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.hints = hints or [
            ("tab", "agents"),
            ("ctrl+p", "commands"),
        ]

    def render(self) -> Text:
        theme = ThemeManager.get_theme()
        text = Text()
        for i, (key, label) in enumerate(self.hints):
            if i > 0:
                text.append("  ", style=theme.text_muted)
            text.append(key, style=theme.text)
            text.append(f" {label}", style=theme.text_muted)
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
