"""Permission request dialog."""

from typing import Any, Dict

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.widgets import Button, Input, Static

from .base import DialogBase

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
    """Permission request dialog with allow-once/always/reject options.

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
        super().__init__(**kwargs)
        self.request = request
        self._stage = "permission"

    def _build_body(self) -> str:
        permission = self.request.get("permission", "unknown")
        metadata = self.request.get("metadata", {})
        patterns = self.request.get("patterns", [])
        lines = []

        if permission == "bash":
            cmd = metadata.get("command", "") or (patterns[0] if patterns else "")
            desc = metadata.get("description", "")
            if desc:
                lines.append(f"[dim]{desc}[/dim]")
            lines.append(f"[bold]{cmd}[/bold]")
        elif permission in ("edit", "write"):
            filepath = metadata.get("filepath", "") or (patterns[0] if patterns else "")
            lines.append(f"[bold]{filepath}[/bold]")
            diff = metadata.get("diff", "")
            if diff:
                diff_lines = diff.split("\n")
                if len(diff_lines) > 10:
                    diff_lines = diff_lines[:10] + ["..."]
                lines.append("\n".join(diff_lines))
        elif permission == "read":
            filepath = metadata.get("filepath", "") or (patterns[0] if patterns else "")
            lines.append(f"-> [bold]{filepath}[/bold]")
        elif permission in ("glob", "grep"):
            pattern = metadata.get("pattern", "") or (patterns[0] if patterns else "")
            lines.append(f"* [bold]{pattern}[/bold]")
        elif permission == "external_directory":
            directory = metadata.get("directory", "") or (patterns[0] if patterns else "")
            lines.append(f"<- [bold]{directory}[/bold]")
        elif permission == "doom_loop":
            lines.append("[bold]Continue after repeated failures[/bold]")
        elif permission == "task":
            subagent = metadata.get("subagent_type", "")
            desc = metadata.get("description", "")
            lines.append(f"# {subagent}")
            if desc:
                lines.append(f"[dim]{desc}[/dim]")
        else:
            tool_name = metadata.get("tool_name", permission)
            lines.append(f"? Call tool: [bold]{tool_name}[/bold]")
            for p in patterns:
                lines.append(f"  {p}")

        return "\n".join(lines) if lines else f"Permission: {permission}"

    def compose(self) -> ComposeResult:
        permission = self.request.get("permission", "unknown")
        icon = _PERMISSION_ICONS.get(permission, "?")

        yield Container(
            Static(f"{icon}  Permission: {permission}", classes="dialog-title perm-type"),
            ScrollableContainer(
                Static(self._build_body(), classes="perm-detail"),
                classes="perm-body",
            ),
            Horizontal(
                Button("Allow once", variant="primary", id="allow-once-btn"),
                Button("Allow always", variant="default", id="allow-always-btn"),
                Button("Reject", variant="error", id="reject-btn"),
                classes="dialog-buttons",
                id="permission-buttons",
            ),
            Vertical(
                Static(
                    "[dim]The following patterns will be remembered for this session:[/dim]",
                    classes="perm-always-info",
                ),
                Static(
                    "\n".join(self.request.get("always", self.request.get("patterns", []))),
                    classes="perm-detail",
                ),
                Horizontal(
                    Button("Confirm", variant="primary", id="always-confirm-btn"),
                    Button("Cancel", variant="default", id="always-cancel-btn"),
                    classes="dialog-buttons",
                ),
                id="always-stage",
            ),
            Vertical(
                Static("[dim]Provide feedback to guide the assistant (optional):[/dim]"),
                Input(placeholder="Feedback message...", id="reject-feedback-input"),
                Horizontal(
                    Button("Send feedback", variant="primary", id="reject-send-btn"),
                    Button("Skip", variant="default", id="reject-skip-btn"),
                    classes="dialog-buttons",
                ),
                id="reject-stage",
            ),
            id="permission-container",
        )

    def on_mount(self) -> None:
        self.query_one("#always-stage").display = False
        self.query_one("#reject-stage").display = False

    def _switch_stage(self, stage: str) -> None:
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
        btn_id = event.button.id

        if btn_id == "allow-once-btn":
            self.dismiss(("once", None))
        elif btn_id == "allow-always-btn":
            self._switch_stage("always")
        elif btn_id == "reject-btn":
            self._switch_stage("reject")
        elif btn_id == "always-confirm-btn":
            self.dismiss(("always", None))
        elif btn_id == "always-cancel-btn":
            self._switch_stage("permission")
        elif btn_id == "reject-send-btn":
            feedback = self.query_one("#reject-feedback-input", Input).value.strip()
            self.dismiss(("reject", feedback or None))
        elif btn_id == "reject-skip-btn":
            self.dismiss(("reject", None))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self._stage == "reject":
            feedback = event.value.strip()
            self.dismiss(("reject", feedback or None))

    def action_cancel(self) -> None:
        self.dismiss(("reject", None))
