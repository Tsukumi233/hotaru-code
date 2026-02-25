"""Base and generic dialog components."""

from typing import Any, List, Tuple

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Input, ListItem, ListView, Static


class DialogBase(ModalScreen):
    """Base class for modal dialogs."""

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
        self.dismiss(None)


class ConfirmDialog(DialogBase):
    """Confirmation dialog with confirm/cancel buttons."""

    def __init__(
        self,
        title: str,
        message: str,
        confirm_label: str = "Confirm",
        cancel_label: str = "Cancel",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.title_text = title
        self.message = message
        self.confirm_label = confirm_label
        self.cancel_label = cancel_label

    def compose(self) -> ComposeResult:
        yield Container(
            Static(self.title_text, classes="dialog-title"),
            Static(self.message, classes="dialog-content"),
            Horizontal(
                Button(self.cancel_label, variant="default", id="cancel-btn"),
                Button(self.confirm_label, variant="primary", id="confirm-btn"),
                classes="dialog-buttons",
            ),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-btn":
            self.dismiss(True)
        else:
            self.dismiss(False)


class AlertDialog(DialogBase):
    """Alert dialog with an OK button."""

    def __init__(self, title: str, message: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.title_text = title
        self.message = message

    def compose(self) -> ComposeResult:
        yield Container(
            Static(self.title_text, classes="dialog-title"),
            Static(self.message, classes="dialog-content"),
            Horizontal(
                Button("OK", variant="primary", id="ok-btn"),
                classes="dialog-buttons",
            ),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(True)


class InputDialog(DialogBase):
    """Input dialog with text field and submit/cancel buttons."""

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
        password: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.title_text = title
        self.placeholder = placeholder
        self.default_value = default_value
        self.submit_label = submit_label
        self.password = password

    def compose(self) -> ComposeResult:
        yield Container(
            Static(self.title_text, classes="dialog-title"),
            Input(
                placeholder=self.placeholder,
                value=self.default_value,
                password=self.password,
                id="dialog-input",
            ),
            Horizontal(
                Button("Cancel", variant="default", id="cancel-btn"),
                Button(self.submit_label, variant="primary", id="submit-btn"),
                classes="dialog-buttons",
            ),
        )

    def on_mount(self) -> None:
        self.query_one("#dialog-input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit-btn":
            self.dismiss(self.query_one("#dialog-input", Input).value)
        else:
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)


class SelectDialog(DialogBase):
    """Selection dialog with a list of options."""

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
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.title_text = title
        self.options = options

    def compose(self) -> ComposeResult:
        yield Container(
            Static(self.title_text, classes="dialog-title"),
            ListView(
                *[
                    ListItem(Static(label), id=f"option-{i}")
                    for i, (label, _) in enumerate(self.options)
                ],
                id="options-list",
            ),
            Horizontal(
                Button("Cancel", variant="default", id="cancel-btn"),
                classes="dialog-buttons",
            ),
        )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item and event.item.id:
            index = int(event.item.id.split("-")[1])
            _, value = self.options[index]
            self.dismiss(value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)
