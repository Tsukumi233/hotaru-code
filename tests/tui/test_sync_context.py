from hotaru.tui.context.sync import SyncContext


def test_set_sessions_sorts_by_updated_descending() -> None:
    ctx = SyncContext()
    ctx.set_sessions(
        [
            {"id": "s1", "time": {"updated": 10}},
            {"id": "s2", "time": {"updated": 100}},
            {"id": "s3", "time": {"updated": 50}},
        ]
    )

    assert [item["id"] for item in ctx.data.sessions] == ["s2", "s3", "s1"]


def test_update_session_keeps_recency_order() -> None:
    ctx = SyncContext()
    ctx.set_sessions(
        [
            {"id": "s1", "time": {"updated": 10}},
            {"id": "s2", "time": {"updated": 100}},
        ]
    )

    ctx.update_session({"id": "s1", "time": {"updated": 200}})
    assert [item["id"] for item in ctx.data.sessions] == ["s1", "s2"]
