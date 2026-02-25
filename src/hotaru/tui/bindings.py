"""Key binding definitions for the TUI application."""

from textual.binding import Binding

APP_BINDINGS = [
    Binding("ctrl+p", "command_palette", "Commands", show=True),
    Binding("ctrl+n", "new_session", "New", show=False),
    Binding("ctrl+s", "session_list", "Sessions", show=False),
    Binding("ctrl+m", "model_list", "Models", show=False),
    Binding("ctrl+a", "agent_list", "Agents", show=False),
    Binding("ctrl+t", "toggle_theme", "Theme", show=False),
    Binding("ctrl+c", "quit", "Quit", show=True, priority=True),
]
