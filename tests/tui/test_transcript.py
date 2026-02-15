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
            "id": "m1",
            "role": "user",
            "info": {"id": "m1", "role": "user", "time": {"created": 1_700_000_000_000, "completed": 1_700_000_000_000}},
            "parts": [{"type": "text", "text": "Hello"}],
        },
        {
            "id": "m2",
            "role": "assistant",
            "info": {
                "id": "m2",
                "role": "assistant",
                "time": {"created": 1_700_000_000_500, "completed": 1_700_000_003_500},
                "model": {"provider_id": "anthropic", "model_id": "claude"},
            },
            "parts": [
                {"type": "text", "text": "Hi there"},
                {"type": "reasoning", "text": "Hidden thoughts"},
                {
                    "type": "tool",
                    "tool": "read",
                    "call_id": "call_1",
                    "state": {
                        "status": "completed",
                        "input": {"path": "README.md"},
                        "output": "ok",
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
    assert "**Tool: read (completed)**" in transcript
    assert '"path": "README.md"' in transcript
    assert "ok" in transcript


def test_transcript_supports_structured_tool_and_step_parts() -> None:
    messages = [
        {
            "id": "m_user",
            "role": "user",
            "info": {"id": "m_user", "role": "user", "time": {"created": 1, "completed": 1}},
            "parts": [{"type": "text", "text": "Build it"}],
        },
        {
            "id": "m_assistant",
            "role": "assistant",
            "info": {
                "id": "m_assistant",
                "role": "assistant",
                "time": {"created": 2, "completed": 6},
                "model": {"provider_id": "openai", "model_id": "gpt-5"},
            },
            "parts": [
                {"type": "step-start"},
                {"type": "reasoning", "text": "Plan first"},
                {
                    "type": "tool",
                    "tool": "bash",
                    "call_id": "call_1",
                    "state": {
                        "status": "completed",
                        "input": {"command": "pytest -q"},
                        "output": "1 passed",
                    },
                },
                {
                    "type": "step-finish",
                    "reason": "stop",
                    "tokens": {"input": 20, "output": 8, "reasoning": 3},
                },
            ],
        },
    ]

    transcript = format_transcript(
        _build_session(),
        messages,
        TranscriptOptions(thinking=True, tool_details=True, assistant_metadata=True),
    )

    assert "## Assistant (openai/gpt-5" in transcript
    assert "_Step started._" in transcript
    assert "**Tool: bash (completed)**" in transcript
    assert "pytest -q" in transcript
    assert "_Step finished: stop._" in transcript
