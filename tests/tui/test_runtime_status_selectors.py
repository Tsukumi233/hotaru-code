from hotaru.tui.context.route import HomeRoute, RouteContext, SessionRoute
from hotaru.tui.context.sync import SyncContext
from hotaru.tui.state.selectors import select_runtime_status


def test_select_runtime_status_counts_lsp_mcp_and_permissions_for_session_route() -> None:
    sync = SyncContext()
    route = RouteContext()
    route.navigate(SessionRoute(session_id="session_1"))

    sync.set_mcp_status(
        {
            "filesystem": {"status": "connected"},
            "docs": {"status": "failed"},
            "notes": {"status": "disabled"},
        }
    )
    sync.set_lsp_status(
        [
            {"id": "pyright", "status": "connected"},
            {"id": "ruff", "status": "error"},
        ]
    )
    sync.add_permission("session_1", {"id": "perm_1"})
    sync.add_permission("session_1", {"id": "perm_2"})

    snapshot = select_runtime_status(sync=sync, route=route)

    assert snapshot.lsp_count == 2
    assert snapshot.mcp_connected == 1
    assert snapshot.mcp_error is True
    assert snapshot.permission_count == 2
    assert snapshot.show_status_hint is True


def test_select_runtime_status_ignores_permissions_outside_session_route() -> None:
    sync = SyncContext()
    route = RouteContext()
    route.navigate(HomeRoute())

    sync.set_lsp_status([{"id": "pyright", "status": "connected"}])
    sync.add_permission("session_1", {"id": "perm_1"})

    snapshot = select_runtime_status(sync=sync, route=route)

    assert snapshot.lsp_count == 1
    assert snapshot.permission_count == 0


def test_select_runtime_status_empty_snapshot_has_no_status_hint() -> None:
    snapshot = select_runtime_status(sync=SyncContext(), route=RouteContext())

    assert snapshot.mcp_connected == 0
    assert snapshot.lsp_count == 0
    assert snapshot.permission_count == 0
    assert snapshot.show_status_hint is False
