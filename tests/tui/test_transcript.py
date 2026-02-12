from hotaru.tui.transcript import TranscriptOptions, format_transcript


def _build_session() -> dict:
    return {
        "id": "session_12345678",
        "title": "Test Session",
        "time": {"created": 1_700_000_000_000, "updated": 1_700_000_100_000},
    }


def _build_messages() -> list[dict]:
    return [
        {
            "role": "user",
            "parts": [{"type": "text", "text": "Hello"}],
        },
        {
            "role": "assistant",
            "metadata": {
                "time": {"created": 1_700_000_000_500, "completed": 1_700_000_003_500},
                "assistant": {"provider_id": "anthropic", "model_id": "claude"},
            },
            "parts": [
                {"type": "text", "text": "Hi there"},
                {"type": "reasoning", "text": "Hidden thoughts"},
                {
                    "type": "tool-invocation",
                    "tool_invocation": {
                        "state": "result",
                        "tool_name": "read",
                        "args": {"path": "README.md"},
                        "result": "ok",
                    },
                },
            ],
        },
    ]


def test_transcript_omits_reasoning_when_disabled() -> None:
    transcript = format_transcript(
        _build_session(),
        _build_messages(),
        TranscriptOptions(thinking=False),
    )

    assert "# Test Session" in transcript
    assert "## User" in transcript
    assert "## Assistant (anthropic/claude · 3.0s)" in transcript
    assert "Hidden thoughts" not in transcript


def test_transcript_includes_reasoning_and_tool_details() -> None:
    transcript = format_transcript(
        _build_session(),
        _build_messages(),
        TranscriptOptions(thinking=True, tool_details=True, assistant_metadata=False),
    )

    assert "## Assistant" in transcript
    assert "_Thinking:_" in transcript
    assert "**Tool: read**" in transcript
    assert '"path": "README.md"' in transcript
    assert "ok" in transcript
