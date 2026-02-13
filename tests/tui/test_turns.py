from hotaru.tui.turns import extract_user_text_from_turn, split_messages_for_undo


def test_split_messages_for_undo_removes_latest_user_turn() -> None:
    messages = [
        {"id": "m1", "role": "user", "parts": [{"type": "text", "text": "first"}]},
        {"id": "m2", "role": "assistant", "parts": [{"type": "text", "text": "ok"}]},
        {"id": "m3", "role": "user", "parts": [{"type": "text", "text": "second"}]},
        {"id": "m4", "role": "assistant", "parts": [{"type": "text", "text": "done"}]},
    ]

    remaining, removed = split_messages_for_undo(messages)

    assert [msg["id"] for msg in remaining] == ["m1", "m2"]
    assert [msg["id"] for msg in removed] == ["m3", "m4"]


def test_split_messages_for_undo_without_user_message_returns_noop() -> None:
    messages = [{"id": "m1", "role": "assistant", "parts": []}]
    remaining, removed = split_messages_for_undo(messages)

    assert remaining == messages
    assert removed == []


def test_extract_user_text_from_turn_returns_text_content() -> None:
    turn = [
        {
            "id": "m3",
            "role": "user",
            "parts": [
                {"type": "text", "text": "hello "},
                {"type": "text", "text": "world"},
                {"type": "file", "url": "file://example"},
            ],
        },
        {"id": "m4", "role": "assistant", "parts": [{"type": "text", "text": "ack"}]},
    ]

    assert extract_user_text_from_turn(turn) == "hello world"
