from hotaru.tui.app import TuiApp
from hotaru.tui.context.route import SessionRoute


def test_continue_last_session_ignores_child_sessions_by_parent_id() -> None:
    app = TuiApp()
    app.sync_ctx.set_sessions(
        [
            {"id": "session_root", "time": {"updated": 10}, "parent_id": None},
            {"id": "session_child", "time": {"updated": 20}, "parent_id": "session_root"},
        ]
    )

    route = app._continue_last_session()
    assert isinstance(route, SessionRoute)
    assert route.session_id == "session_root"
