"""Message display widgets: MessageBubble, AssistantTextPart."""

from typing import Optional

from textual.widgets import Static
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from ..theme import ThemeManager


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
