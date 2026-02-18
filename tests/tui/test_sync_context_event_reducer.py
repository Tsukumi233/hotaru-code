from hotaru.tui.context.sync import SyncContext, SyncEvent


def test_runtime_event_reducer_supports_part_before_message() -> None:
    sync = SyncContext()

    sync.apply_runtime_event(
        "message.part.updated",
        {
            "part": {
                "id": "part_1",
                "session_id": "session_1",
                "message_id": "message_1",
                "type": "text",
                "text": "Hel",
            }
        },
    )
    sync.apply_runtime_event(
        "message.part.delta",
        {
            "session_id": "session_1",
            "message_id": "message_1",
            "part_id": "part_1",
            "field": "text",
            "delta": "lo",
        },
    )
    sync.apply_runtime_event(
        "message.updated",
        {
            "info": {
                "id": "message_1",
                "session_id": "session_1",
                "role": "assistant",
                "agent": "build",
            }
        },
    )

    messages = sync.get_messages("session_1")
    assert len(messages) == 1
    assert messages[0]["role"] == "assistant"
    assert messages[0]["info"]["agent"] == "build"
    assert messages[0]["parts"][0]["text"] == "Hello"


def test_runtime_event_reducer_tracks_user_messages() -> None:
    sync = SyncContext()

    sync.apply_runtime_event(
        "message.updated",
        {
            "info": {
                "id": "message_user_1",
                "session_id": "session_1",
                "role": "user",
            }
        },
    )
    sync.apply_runtime_event(
        "message.part.updated",
        {
            "part": {
                "id": "part_user_1",
                "session_id": "session_1",
                "message_id": "message_user_1",
                "type": "text",
                "text": "hello",
            }
        },
    )

    messages = sync.get_messages("session_1")
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert messages[0]["parts"][0]["text"] == "hello"


def test_runtime_event_reducer_emits_sync_events() -> None:
    sync = SyncContext()
    seen: list[str] = []

    sync.on(SyncEvent.MESSAGE_UPDATED, lambda _payload: seen.append("message"))
    sync.on(SyncEvent.PART_UPDATED, lambda _payload: seen.append("part"))

    sync.apply_runtime_event(
        "message.updated",
        {
            "info": {
                "id": "message_1",
                "session_id": "session_1",
                "role": "assistant",
            }
        },
    )
    sync.apply_runtime_event(
        "message.part.updated",
        {
            "part": {
                "id": "part_1",
                "session_id": "session_1",
                "message_id": "message_1",
                "type": "text",
                "text": "ok",
            }
        },
    )

    assert seen == ["message", "part"]
