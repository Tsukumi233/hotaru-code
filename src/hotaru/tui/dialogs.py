"""Dialog components for TUI.

This module provides modal dialog components for the TUI,
including model selection, session list, and confirmation dialogs.
"""

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import Static, Input, Button, ListView, ListItem
from textual.binding import Binding
from rich.text import Text
from typing import Any, Dict, List, Optional, Tuple


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
        password: bool = False,
        **kwargs
    ) -> None:
        """Initialize input dialog.

        Args:
            title: Dialog title
            placeholder: Input placeholder text
            default_value: Default input value
            submit_label: Label for submit button
            password: Whether to hide typed input
        """
        super().__init__(**kwargs)
        self.title_text = title
        self.placeholder = placeholder
        self.default_value = default_value
        self.submit_label = submit_label
        self.password = password

    def compose(self) -> ComposeResult:
        """Compose the dialog."""
        yield Container(
            Static(self.title_text, classes="dialog-title"),
            Input(
                placeholder=self.placeholder,
                value=self.default_value,
                password=self.password,
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
        self._model_options: List[Tuple[str, str]] = []

    def compose(self) -> ComposeResult:
        """Compose the dialog."""
        items = []
        self._model_options = []
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
                option_index = len(self._model_options)
                self._model_options.append((provider_id, model_id))
                items.append(
                    ListItem(
                        Static(label),
                        id=f"model-option-{option_index}",
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
        if not event.item or not event.item.id:
            return
        if not event.item.id.startswith("model-option-"):
            return

        try:
            index = int(event.item.id.split("-")[-1])
        except ValueError:
            return

        if 0 <= index < len(self._model_options):
            self.dismiss(self._model_options[index])

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


class AgentSelectDialog(DialogBase):
    """Agent selection dialog."""

    DEFAULT_CSS = DialogBase.DEFAULT_CSS + """
    AgentSelectDialog > Container {
        width: 70;
    }

    AgentSelectDialog ListView {
        height: auto;
        max-height: 20;
    }
    """

    def __init__(
        self,
        agents: List[Dict[str, Any]],
        current_agent: Optional[str] = None,
        **kwargs
    ) -> None:
        super().__init__(**kwargs)
        self.agents = agents
        self.current_agent = current_agent

    def compose(self) -> ComposeResult:
        items = []
        for agent in self.agents:
            name = agent.get("name", "")
            description = agent.get("description", "")
            marker = "● " if name == self.current_agent else "  "
            label = Text()
            label.append(f"{marker}{name}", style="bold")
            if description:
                label.append(f"\n  {description}", style="dim")
            items.append(ListItem(Static(label), id=f"agent-{name}"))

        yield Container(
            Static("Select Agent", classes="dialog-title"),
            ListView(*items, id="agents-list") if items else Static("No agents found"),
            Horizontal(
                Button("Cancel", variant="default", id="cancel-btn"),
                classes="dialog-buttons"
            )
        )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item and event.item.id and event.item.id.startswith("agent-"):
            self.dismiss(event.item.id[6:])

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)


class StatusDialog(DialogBase):
    """Runtime status dialog for model, agent, MCP, and LSP state."""

    DEFAULT_CSS = DialogBase.DEFAULT_CSS + """
    StatusDialog > Container {
        width: 76;
        max-height: 85%;
    }

    StatusDialog .status-content {
        height: auto;
        max-height: 24;
        padding: 0 1;
        margin-bottom: 1;
        background: $surface-darken-1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Close"),
        Binding("r", "refresh", "Refresh"),
    ]

    def __init__(
        self,
        model: str,
        agent: str,
        mcp: Dict[str, Dict[str, Any]],
        lsp: List[Dict[str, Any]],
        **kwargs
    ) -> None:
        super().__init__(**kwargs)
        self.model = model
        self.agent = agent
        self.mcp = mcp
        self.lsp = lsp

    def compose(self) -> ComposeResult:
        lines = []
        lines.append("[bold]Current Selection[/bold]")
        lines.append(f"Agent: {self.agent}")
        lines.append(f"Model: {self.model}")
        lines.append("")

        lines.append("[bold]MCP[/bold]")
        if self.mcp:
            for name in sorted(self.mcp.keys()):
                status = self.mcp[name].get("status", "unknown")
                error = self.mcp[name].get("error")
                line = f"- {name}: {status}"
                if error:
                    line += f" ({error})"
                lines.append(line)
        else:
            lines.append("- No MCP servers configured")
        lines.append("")

        lines.append("[bold]LSP[/bold]")
        if self.lsp:
            for server in self.lsp:
                name = server.get("name", server.get("id", "unknown"))
                root = server.get("root", ".")
                status = server.get("status", "unknown")
                lines.append(f"- {name} @ {root}: {status}")
        else:
            lines.append("- No active LSP servers")

        yield Container(
            Static("Runtime Status", classes="dialog-title"),
            ScrollableContainer(
                Static("\n".join(lines), classes="status-content"),
                classes="dialog-content",
            ),
            Horizontal(
                Button("Refresh", variant="default", id="refresh-btn"),
                Button("Close", variant="primary", id="close-btn"),
                classes="dialog-buttons"
            )
        )

    def action_refresh(self) -> None:
        self.dismiss("refresh")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "refresh-btn":
            self.dismiss("refresh")
            return
        self.dismiss(True)


# Permission type icons
_PERMISSION_ICONS = {
    "bash": "#",
    "edit": "~",
    "write": "~",
    "read": "->",
    "glob": "*",
    "grep": "*",
    "list": "->",
    "task": "#",
    "webfetch": "%",
    "websearch": "<>",
    "codesearch": "<>",
    "todowrite": "+",
    "todoread": "->",
    "question": "?",
    "batch": "||",
    "apply_patch": "~",
    "lsp": "<>",
    "plan_enter": "P",
    "plan_exit": "P",
    "external_directory": "<-",
    "doom_loop": ">>",
}


class PermissionDialog(DialogBase):
    """Permission request dialog.

    Shows a permission request with allow-once/always/reject options.
    Has three stages: permission, always-confirmation, and reject-feedback.

    Dismisses with:
        ("once", None) - allow once
        ("always", None) - allow always (after confirmation)
        ("reject", message_or_none) - reject, optionally with feedback
    """

    DEFAULT_CSS = DialogBase.DEFAULT_CSS + """
    PermissionDialog > Container {
        width: 70;
        height: auto;
        max-height: 80%;
    }

    PermissionDialog .perm-type {
        text-style: bold;
        color: $accent;
        padding-bottom: 1;
    }

    PermissionDialog .perm-body {
        height: auto;
        max-height: 15;
        padding: 0 1;
        margin-bottom: 1;
        background: $surface-darken-1;
    }

    PermissionDialog .perm-detail {
        color: $text;
    }

    PermissionDialog .perm-label {
        color: $text-muted;
    }

    PermissionDialog .perm-always-info {
        padding: 1;
        margin-bottom: 1;
    }

    PermissionDialog Input {
        width: 100%;
        margin-bottom: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, request: Dict[str, Any], **kwargs) -> None:
        """Initialize permission dialog.

        Args:
            request: Permission request data (dict from PermissionRequest.model_dump())
        """
        super().__init__(**kwargs)
        self.request = request
        self._stage = "permission"  # "permission" | "always" | "reject"

    def compose(self) -> ComposeResult:
        """Compose the dialog."""
        permission = self.request.get("permission", "unknown")
        icon = _PERMISSION_ICONS.get(permission, "?")
        metadata = self.request.get("metadata", {})
        patterns = self.request.get("patterns", [])

        # Build the body text based on permission type
        body_lines = []
        if permission == "bash":
            cmd = metadata.get("command", "") or (patterns[0] if patterns else "")
            desc = metadata.get("description", "")
            if desc:
                body_lines.append(f"[dim]{desc}[/dim]")
            body_lines.append(f"[bold]{cmd}[/bold]")
        elif permission in ("edit", "write"):
            filepath = metadata.get("filepath", "") or (patterns[0] if patterns else "")
            body_lines.append(f"[bold]{filepath}[/bold]")
            diff = metadata.get("diff", "")
            if diff:
                # Show a truncated diff
                diff_lines = diff.split("\n")
                if len(diff_lines) > 10:
                    diff_lines = diff_lines[:10] + ["..."]
                body_lines.append("\n".join(diff_lines))
        elif permission == "read":
            filepath = metadata.get("filepath", "") or (patterns[0] if patterns else "")
            body_lines.append(f"-> [bold]{filepath}[/bold]")
        elif permission in ("glob", "grep"):
            pattern = metadata.get("pattern", "") or (patterns[0] if patterns else "")
            body_lines.append(f"* [bold]{pattern}[/bold]")
        elif permission == "external_directory":
            directory = metadata.get("directory", "") or (patterns[0] if patterns else "")
            body_lines.append(f"<- [bold]{directory}[/bold]")
        elif permission == "doom_loop":
            body_lines.append("[bold]Continue after repeated failures[/bold]")
        elif permission == "task":
            subagent = metadata.get("subagent_type", "")
            desc = metadata.get("description", "")
            body_lines.append(f"# {subagent}")
            if desc:
                body_lines.append(f"[dim]{desc}[/dim]")
        else:
            tool_name = metadata.get("tool_name", permission)
            body_lines.append(f"? Call tool: [bold]{tool_name}[/bold]")
            for p in patterns:
                body_lines.append(f"  {p}")

        body_text = "\n".join(body_lines) if body_lines else f"Permission: {permission}"

        yield Container(
            Static(f"{icon}  Permission: {permission}", classes="dialog-title perm-type"),
            ScrollableContainer(
                Static(body_text, classes="perm-detail"),
                classes="perm-body",
            ),
            # Stage: permission buttons
            Horizontal(
                Button("Allow once", variant="primary", id="allow-once-btn"),
                Button("Allow always", variant="default", id="allow-always-btn"),
                Button("Reject", variant="error", id="reject-btn"),
                classes="dialog-buttons",
                id="permission-buttons",
            ),
            # Stage: always confirmation (hidden initially)
            Vertical(
                Static(
                    "[dim]The following patterns will be remembered for this session:[/dim]",
                    classes="perm-always-info"
                ),
                Static(
                    "\n".join(self.request.get("always", self.request.get("patterns", []))),
                    classes="perm-detail"
                ),
                Horizontal(
                    Button("Confirm", variant="primary", id="always-confirm-btn"),
                    Button("Cancel", variant="default", id="always-cancel-btn"),
                    classes="dialog-buttons"
                ),
                id="always-stage",
            ),
            # Stage: reject with feedback (hidden initially)
            Vertical(
                Static("[dim]Provide feedback to guide the assistant (optional):[/dim]"),
                Input(
                    placeholder="Feedback message...",
                    id="reject-feedback-input"
                ),
                Horizontal(
                    Button("Send feedback", variant="primary", id="reject-send-btn"),
                    Button("Skip", variant="default", id="reject-skip-btn"),
                    classes="dialog-buttons"
                ),
                id="reject-stage",
            ),
            id="permission-container",
        )

    def on_mount(self) -> None:
        """Handle mount — show only the permission stage initially."""
        self.query_one("#always-stage").display = False
        self.query_one("#reject-stage").display = False

    def _switch_stage(self, stage: str) -> None:
        """Switch to a dialog stage."""
        self._stage = stage
        self.query_one("#permission-buttons").display = (stage == "permission")
        self.query_one("#always-stage").display = (stage == "always")
        self.query_one("#reject-stage").display = (stage == "reject")
        if stage == "reject":
            try:
                self.query_one("#reject-feedback-input", Input).focus()
            except Exception:
                pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        btn_id = event.button.id

        # Permission stage
        if btn_id == "allow-once-btn":
            self.dismiss(("once", None))
        elif btn_id == "allow-always-btn":
            self._switch_stage("always")
        elif btn_id == "reject-btn":
            self._switch_stage("reject")

        # Always confirmation stage
        elif btn_id == "always-confirm-btn":
            self.dismiss(("always", None))
        elif btn_id == "always-cancel-btn":
            self._switch_stage("permission")

        # Reject feedback stage
        elif btn_id == "reject-send-btn":
            feedback = self.query_one("#reject-feedback-input", Input).value.strip()
            self.dismiss(("reject", feedback or None))
        elif btn_id == "reject-skip-btn":
            self.dismiss(("reject", None))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter in feedback input."""
        if self._stage == "reject":
            feedback = event.value.strip()
            self.dismiss(("reject", feedback or None))

    def action_cancel(self) -> None:
        """Cancel and close the dialog (Escape key)."""
        self.dismiss(("reject", None))
