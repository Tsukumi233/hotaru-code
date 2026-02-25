"""Layout widgets: AppFooter, SessionHeaderBar, PromptMeta, PromptHints, SessionListItem."""

from typing import List, Optional

from textual.app import ComposeResult
from textual.widgets import Static, ListItem
from rich.text import Text

from ..theme import ThemeManager
from ..state.runtime_status import RuntimeStatusSnapshot


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
        text.append(self.directory, style=theme.text_muted)

        right_parts: List[Text] = []

        if self.permission_count > 0:
            perm = Text()
            perm.append("\u25b3", style=theme.warning)
            suffix = "s" if self.permission_count != 1 else ""
            perm.append(f" {self.permission_count} Permission{suffix}", style=theme.text)
            right_parts.append(perm)

        if self.show_lsp:
            lsp = Text()
            dot_color = theme.success if self.lsp_count > 0 else theme.text_muted
            lsp.append("\u2022", style=dot_color)
            lsp.append(f" {self.lsp_count} LSP", style=theme.text)
            right_parts.append(lsp)

        if self.mcp_connected > 0 or self.mcp_error:
            mcp = Text()
            icon_color = theme.error if self.mcp_error else theme.success
            mcp.append("\u2299", style=icon_color)
            mcp.append(f" {self.mcp_connected} MCP", style=theme.text)
            right_parts.append(mcp)

        should_show_status_hint = self.show_status_hint or bool(right_parts)
        if should_show_status_hint:
            right_parts.append(Text("/status", style=theme.text_muted))

        if self.version:
            right_parts.append(Text(self.version, style=theme.text_muted))

        if right_parts:
            right_text = Text("  ").join(right_parts)
            available = self.size.width - len(self.directory) - 4
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
        text.append("# ", style=f"bold {theme.text}")
        text.append(self.title, style=f"bold {theme.text}")
        if self.context_info:
            right = Text()
            right.append(self.context_info, style=theme.text_muted)
            if self.cost:
                right.append(f" ({self.cost})", style=theme.text_muted)
            available = self.size.width - len(self.title) - 6
            if available > len(right):
                text.append(" " * (available - len(right)))
            else:
                text.append("  ")
            text.append_text(right)
        return text

    # -- PromptMeta, PromptHints, SessionListItem --


class PromptMeta(Static):
    """Agent name + model info displayed below the prompt input."""

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
    """Keyboard hint bar displayed below the prompt meta line."""

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
