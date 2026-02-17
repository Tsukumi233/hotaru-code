from hotaru.tui.context.sync import SyncContext, SyncEvent


def test_set_lsp_status_emits_legacy_and_runtime_events() -> None:
    sync = SyncContext()
    calls: list[tuple[str, object]] = []

    sync.on("lsp", lambda payload: calls.append(("legacy", payload)))
    sync.on(SyncEvent.LSP_UPDATED, lambda payload: calls.append(("runtime", payload)))

    payload = [{"id": "pyright", "status": "connected"}]
    sync.set_lsp_status(payload)

    assert ("legacy", payload) in calls
    assert ("runtime", payload) in calls


def test_set_mcp_status_emits_legacy_and_runtime_events() -> None:
    sync = SyncContext()
    calls: list[tuple[str, object]] = []

    sync.on("mcp", lambda payload: calls.append(("legacy", payload)))
    sync.on(SyncEvent.MCP_UPDATED, lambda payload: calls.append(("runtime", payload)))

    payload = {"filesystem": {"status": "connected"}}
    sync.set_mcp_status(payload)

    assert ("legacy", payload) in calls
    assert ("runtime", payload) in calls
