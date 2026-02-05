"""Dialog components for TUI.

This module provides modal dialog components for the TUI,
including model selection, session list, and confirmation dialogs.
"""

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import Static, Input, Button, Label, ListView, ListItem
from textual.binding import Binding
from rich.text import Text
from rich.panel import Panel
from typing import Any, Callable, Dict, List, Optional, Tuple

from .theme import ThemeManager
from .widgets import Spinner


class DialogBase(ModalScreen):
    """Base class for modal dialogs.

    Provides common styling and behavior for all dialogs.
    """

    DEFAULT_CSS = """
    DialogBase {
        align: center middle;
    }

    DialogBase > Container {
        width: 60;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }

    DialogBase .dialog-title {
        text-style: bold;
        padding-bottom: 1;
    }

    DialogBase .dialog-content {
        height: auto;
        max-height: 20;
    }

    DialogBase .dialog-buttons {
        height: 3;
        align: right middle;
        padding-top: 1;
    }

    DialogBase Button {
        margin-left: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def action_cancel(self) -> None:
        """Cancel and close the dialog."""
        self.dismiss(None)


class ConfirmDialog(DialogBase):
    """Confirmation dialog.

    Shows a message and asks for confirmation.
    """

    def __init__(
        self,
        title: str,
        message: str,
        confirm_label: str = "Confirm",
        cancel_label: str = "Cancel",
        **kwargs
    ) -> None:
        """Initialize confirmation dialog.

        Args:
            title: Dialog title
            message: Message to display
            confirm_label: Label for confirm button
            cancel_label: Label for cancel button
        """
        super().__init__(**kwargs)
        self.title_text = title
        self.message = message
        self.confirm_label = confirm_label
        self.cancel_label = cancel_label

    def compose(self) -> ComposeResult:
        """Compose the dialog."""
        yield Container(
            Static(self.title_text, classes="dialog-title"),
            Static(self.message, classes="dialog-content"),
            Horizontal(
                Button(self.cancel_label, variant="default", id="cancel-btn"),
                Button(self.confirm_label, variant="primary", id="confirm-btn"),
                classes="dialog-buttons"
            )
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        if event.button.id == "confirm-btn":
            self.dismiss(True)
        else:
            self.dismiss(False)


class AlertDialog(DialogBase):
    """Alert dialog.

    Shows a message with an OK button.
    """

    def __init__(
        self,
        title: str,
        message: str,
        **kwargs
    ) -> None:
        """Initialize alert dialog.

        Args:
            title: Dialog title
            message: Message to display
        """
        super().__init__(**kwargs)
        self.title_text = title
        self.message = message

    def compose(self) -> ComposeResult:
        """Compose the dialog."""
        yield Container(
            Static(self.title_text, classes="dialog-title"),
            Static(self.message, classes="dialog-content"),
            Horizontal(
                Button("OK", variant="primary", id="ok-btn"),
                classes="dialog-buttons"
            )
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        self.dismiss(True)


class InputDialog(DialogBase):
    """Input dialog.

    Shows a text input field with submit/cancel buttons.
    """

    DEFAULT_CSS = DialogBase.DEFAULT_CSS + """
    InputDialog Input {
        width: 100%;
        margin-bottom: 1;
    }
    """

    def __init__(
        self,
        title: str,
        placeholder: str = "",
        default_value: str = "",
        submit_label: str = "Submit",
        **kwargs
    ) -> None:
        """Initialize input dialog.

        Args:
            title: Dialog title
            placeholder: Input placeholder text
            default_value: Default input value
            submit_label: Label for submit button
        """
        super().__init__(**kwargs)
        self.title_text = title
        self.placeholder = placeholder
        self.default_value = default_value
        self.submit_label = submit_label

    def compose(self) -> ComposeResult:
        """Compose the dialog."""
        yield Container(
            Static(self.title_text, classes="dialog-title"),
            Input(
                placeholder=self.placeholder,
                value=self.default_value,
                id="dialog-input"
            ),
            Horizontal(
                Button("Cancel", variant="default", id="cancel-btn"),
                Button(self.submit_label, variant="primary", id="submit-btn"),
                classes="dialog-buttons"
            )
        )

    def on_mount(self) -> None:
        """Handle mount event."""
        self.query_one("#dialog-input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        if event.button.id == "submit-btn":
            value = self.query_one("#dialog-input", Input).value
            self.dismiss(value)
        else:
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission."""
        self.dismiss(event.value)


class SelectDialog(DialogBase):
    """Selection dialog.

    Shows a list of options to select from.
    """

    DEFAULT_CSS = DialogBase.DEFAULT_CSS + """
    SelectDialog ListView {
        height: auto;
        max-height: 15;
        margin-bottom: 1;
    }

    SelectDialog ListItem {
        padding: 0 1;
    }

    SelectDialog ListItem:hover {
        background: $accent 20%;
    }

    SelectDialog ListItem.-selected {
        background: $accent 40%;
    }
    """

    def __init__(
        self,
        title: str,
        options: List[Tuple[str, Any]],
        **kwargs
    ) -> None:
        """Initialize selection dialog.

        Args:
            title: Dialog title
            options: List of (label, value) tuples
        """
        super().__init__(**kwargs)
        self.title_text = title
        self.options = options

    def compose(self) -> ComposeResult:
        """Compose the dialog."""
        yield Container(
            Static(self.title_text, classes="dialog-title"),
            ListView(
                *[ListItem(Static(label), id=f"option-{i}")
                  for i, (label, _) in enumerate(self.options)],
                id="options-list"
            ),
            Horizontal(
                Button("Cancel", variant="default", id="cancel-btn"),
                classes="dialog-buttons"
            )
        )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle list item selection."""
        if event.item and event.item.id:
            index = int(event.item.id.split("-")[1])
            _, value = self.options[index]
            self.dismiss(value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        self.dismiss(None)


class ModelSelectDialog(DialogBase):
    """Model selection dialog.

    Shows available models grouped by provider.
    """

    DEFAULT_CSS = DialogBase.DEFAULT_CSS + """
    ModelSelectDialog > Container {
        width: 70;
    }

    ModelSelectDialog .provider-section {
        margin-bottom: 1;
    }

    ModelSelectDialog .provider-name {
        text-style: bold;
        color: $text-muted;
    }

    ModelSelectDialog ListView {
        height: auto;
        max-height: 20;
    }

    ModelSelectDialog ListItem {
        padding: 0 1;
    }
    """

    def __init__(
        self,
        providers: Dict[str, List[Dict[str, Any]]],
        current_model: Optional[Tuple[str, str]] = None,
        **kwargs
    ) -> None:
        """Initialize model selection dialog.

        Args:
            providers: Dict of provider_id -> list of model dicts
            current_model: Currently selected (provider_id, model_id)
        """
        super().__init__(**kwargs)
        self.providers = providers
        self.current_model = current_model

    def compose(self) -> ComposeResult:
        """Compose the dialog."""
        theme = ThemeManager.get_theme()

        items = []
        for provider_id, models in self.providers.items():
            # Add provider header
            items.append(
                ListItem(
                    Static(f"── {provider_id} ──", classes="provider-name"),
                    disabled=True
                )
            )
            # Add models
            for model in models:
                model_id = model.get("id", "")
                model_name = model.get("name", model_id)
                is_current = (
                    self.current_model and
                    self.current_model[0] == provider_id and
                    self.current_model[1] == model_id
                )
                label = f"{'● ' if is_current else '  '}{model_name}"
                items.append(
                    ListItem(
                        Static(label),
                        id=f"model-{provider_id}-{model_id}"
                    )
                )

        yield Container(
            Static("Select Model", classes="dialog-title"),
            ListView(*items, id="models-list"),
            Horizontal(
                Button("Cancel", variant="default", id="cancel-btn"),
                classes="dialog-buttons"
            )
        )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle model selection."""
        if event.item and event.item.id and event.item.id.startswith("model-"):
            parts = event.item.id.split("-", 2)
            if len(parts) == 3:
                provider_id = parts[1]
                model_id = parts[2]
                self.dismiss((provider_id, model_id))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        self.dismiss(None)


class SessionListDialog(DialogBase):
    """Session list dialog.

    Shows available sessions to switch to.
    """

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
        **kwargs
    ) -> None:
        """Initialize session list dialog.

        Args:
            sessions: List of session dicts
            current_session_id: Currently active session ID
        """
        super().__init__(**kwargs)
        self.sessions = sessions
        self.current_session_id = current_session_id

    def compose(self) -> ComposeResult:
        """Compose the dialog."""
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
                    classes="session-item"
                )
            )

        yield Container(
            Static("Switch Session", classes="dialog-title"),
            ListView(*items, id="sessions-list") if items else Static("No sessions found"),
            Horizontal(
                Button("New Session", variant="primary", id="new-btn"),
                Button("Cancel", variant="default", id="cancel-btn"),
                classes="dialog-buttons"
            )
        )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle session selection."""
        if event.item and event.item.id and event.item.id.startswith("session-"):
            session_id = event.item.id[8:]  # Remove "session-" prefix
            self.dismiss(("select", session_id))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        if event.button.id == "new-btn":
            self.dismiss(("new", None))
        else:
            self.dismiss(None)


class HelpDialog(DialogBase):
    """Help dialog.

    Shows keyboard shortcuts and available commands.
    """

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

  [cyan]Ctrl+X[/cyan]     Open command palette
  [cyan]Ctrl+N[/cyan]     New session
  [cyan]Ctrl+S[/cyan]     Switch session
  [cyan]Ctrl+M[/cyan]     Switch model
  [cyan]Ctrl+A[/cyan]     Switch agent
  [cyan]Ctrl+T[/cyan]     Toggle theme
  [cyan]Ctrl+Q[/cyan]     Quit

[bold]Slash Commands[/bold]

  [cyan]/new[/cyan]       Start new session
  [cyan]/sessions[/cyan]  List sessions
  [cyan]/models[/cyan]    List models
  [cyan]/agents[/cyan]    List agents
  [cyan]/status[/cyan]    View status
  [cyan]/help[/cyan]      Show this help
  [cyan]/exit[/cyan]      Exit application

[bold]Navigation[/bold]

  [cyan]PageUp/Down[/cyan]   Scroll messages
  [cyan]Home/End[/cyan]      Jump to first/last message
  [cyan]Escape[/cyan]        Go back / Close dialog
"""

    def compose(self) -> ComposeResult:
        """Compose the dialog."""
        from rich.markdown import Markdown

        yield Container(
            Static("Help", classes="dialog-title"),
            ScrollableContainer(
                Static(self.HELP_CONTENT),
                classes="dialog-content"
            ),
            Horizontal(
                Button("Close", variant="primary", id="close-btn"),
                classes="dialog-buttons"
            )
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        self.dismiss(True)
