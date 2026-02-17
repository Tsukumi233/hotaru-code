from hotaru.tui.state.runtime_status import RuntimeStatusSnapshot
from hotaru.tui.widgets import AppFooter


def test_app_footer_renders_runtime_snapshot_for_session_mode() -> None:
    footer = AppFooter(directory="/repo", version="1.2.3", show_lsp=True)
    footer.apply_runtime_snapshot(
        RuntimeStatusSnapshot(
            mcp_connected=2,
            mcp_error=False,
            lsp_count=3,
            permission_count=1,
            show_status_hint=True,
        )
    )

    rendered = footer.render().plain

    assert "/repo" in rendered
    assert "3 LSP" in rendered
    assert "2 MCP" in rendered
    assert "1 Permission" in rendered
    assert "/status" in rendered
    assert "1.2.3" in rendered
