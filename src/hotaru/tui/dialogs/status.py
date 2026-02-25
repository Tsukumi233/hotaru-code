"""Runtime status dialog."""

from typing import Any, Dict, List, Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, ScrollableContainer
from textual.widgets import Button, Static

from ..state.runtime_status import RuntimeStatusSnapshot
from .base import DialogBase


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
        mcp: Optional[Dict[str, Dict[str, Any]]] = None,
        lsp: Optional[List[Dict[str, Any]]] = None,
        runtime: Optional[RuntimeStatusSnapshot] = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.model = model
        self.agent = agent
        self.runtime = runtime
        if runtime is not None:
            self.mcp = runtime.mcp
            self.lsp = runtime.lsp
        else:
            self.mcp = mcp or {}
            self.lsp = lsp or []

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
                classes="dialog-buttons",
            ),
        )

    def action_refresh(self) -> None:
        self.dismiss("refresh")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "refresh-btn":
            self.dismiss("refresh")
            return
        self.dismiss(True)
