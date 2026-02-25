"""Common utility widgets: Logo, Toast, Spinner."""

from typing import List, Optional

from textual.reactive import reactive
from textual.widgets import Static
from rich.panel import Panel
from rich.text import Text

from ..theme import ThemeManager


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
        super().__init__(**kwargs)
        self.message = message
        self.variant = variant
        self.title = title

    def render(self) -> Panel:
        """Render the toast."""
        theme = ThemeManager.get_theme()
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
