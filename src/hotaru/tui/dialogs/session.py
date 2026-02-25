"""Session list and help dialogs."""

from typing import Any, Dict, List, Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, ScrollableContainer
from textual.widgets import Button, ListItem, ListView, Static

from .base import DialogBase


class SessionListDialog(DialogBase):
    """Session list dialog for switching sessions."""

    DEFAULT_CSS = DialogBase.DEFAULT_CSS + """
    SessionListDialog > Container {
        width: 70;
    }

    SessionListDialog ListView {
        height: auto;
        max-height: 20;
    }

    SessionListDialog .session-item {
        padding: 0 1;
    }

    SessionListDialog .session-title {
        text-style: bold;
    }

    SessionListDialog .session-meta {
        color: $text-muted;
    }
    """

    def __init__(
        self,
        sessions: List[Dict[str, Any]],
        current_session_id: Optional[str] = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.sessions = sessions
        self.current_session_id = current_session_id

    def compose(self) -> ComposeResult:
        items = []
        for session in self.sessions:
            session_id = session.get("id", "")
            title = session.get("title", "Untitled")
            updated = session.get("updated", "")
            is_current = session_id == self.current_session_id

            label = Text()
            if is_current:
                label.append("● ", style="bold green")
            label.append(title, style="bold")
            label.append(f"\n  {updated}", style="dim")

            items.append(
                ListItem(
                    Static(label),
                    id=f"session-{session_id}",
                    classes="session-item",
                )
            )

        yield Container(
            Static("Switch Session", classes="dialog-title"),
            ListView(*items, id="sessions-list") if items else Static("No sessions found"),
            Horizontal(
                Button("New Session", variant="primary", id="new-btn"),
                Button("Cancel", variant="default", id="cancel-btn"),
                classes="dialog-buttons",
            ),
        )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item and event.item.id and event.item.id.startswith("session-"):
            self.dismiss(("select", event.item.id[8:]))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "new-btn":
            self.dismiss(("new", None))
        else:
            self.dismiss(None)


class HelpDialog(DialogBase):
    """Help dialog showing keyboard shortcuts and commands."""

    DEFAULT_CSS = DialogBase.DEFAULT_CSS + """
    HelpDialog > Container {
        width: 70;
        height: 30;
    }

    HelpDialog .help-section {
        margin-bottom: 1;
    }

    HelpDialog .help-title {
        text-style: bold;
        color: $accent;
    }

    HelpDialog .help-item {
        padding-left: 2;
    }

    HelpDialog .keybind {
        color: $primary;
        text-style: bold;
    }
    """

    HELP_CONTENT = """
[bold]Keyboard Shortcuts[/bold]

  [cyan]Ctrl+P[/cyan]     Open command palette
  [cyan]Ctrl+N[/cyan]     New session
  [cyan]Ctrl+S[/cyan]     Switch session
  [cyan]Ctrl+Z[/cyan]     Undo last turn
  [cyan]Ctrl+Y[/cyan]     Redo undone turn
  [cyan]Ctrl+M[/cyan]     Switch model
  [cyan]Ctrl+A[/cyan]     Switch agent
  [cyan]Ctrl+T[/cyan]     Toggle theme
  [cyan]Ctrl+C[/cyan]     Quit

[bold]Slash Commands[/bold]

  [cyan]/new[/cyan]       Start new session
  [cyan]/init[/cyan]      Generate/update AGENTS.md
  [cyan]/sessions[/cyan]  List sessions
  [cyan]/undo[/cyan]      Undo last turn
  [cyan]/redo[/cyan]      Redo undone turn
  [cyan]/rename[/cyan]    Rename current session (supports /rename <title>)
  [cyan]/models[/cyan]    List models
  [cyan]/connect[/cyan]   Connect provider
  [cyan]/agents[/cyan]    List agents
  [cyan]/copy[/cyan]      Copy session transcript
  [cyan]/export[/cyan]    Export session transcript
  [cyan]/share[/cyan]     Share session snapshot
  [cyan]/mcps[/cyan]      View MCP status
  [cyan]/status[/cyan]    View status
  [cyan]/help[/cyan]      Show this help
  [cyan]/exit[/cyan]      Exit application

[bold]Navigation[/bold]

  [cyan]PageUp/Down[/cyan]   Scroll messages
  [cyan]Home/End[/cyan]      Jump to first/last message
  [cyan]Escape[/cyan]        Go back / Close dialog

[bold]Prompt Input[/bold]

  [cyan]@path[/cyan]         Attach UTF-8 file content to your prompt
  [cyan]!command[/cyan]      Run a local shell command in-session
"""

    def compose(self) -> ComposeResult:
        yield Container(
            Static("Help", classes="dialog-title"),
            ScrollableContainer(
                Static(self.HELP_CONTENT),
                classes="dialog-content",
            ),
            Horizontal(
                Button("Close", variant="primary", id="close-btn"),
                classes="dialog-buttons",
            ),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(True)
