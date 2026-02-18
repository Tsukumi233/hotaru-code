import pytest

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


class _FakeSDK:
    def __init__(self) -> None:
        self.get_session_calls: list[str] = []
        self.get_messages_calls: list[str] = []

    async def get_session(self, session_id: str):
        self.get_session_calls.append(session_id)
        return {
            "id": session_id,
            "title": "Demo Session",
            "agent": "build",
            "time": {"created": 1, "updated": 2},
        }

    async def get_messages(self, session_id: str):
        self.get_messages_calls.append(session_id)
        return [
            {"id": "m_user", "role": "user", "info": {"id": "m_user"}, "parts": [{"type": "text", "text": "hello"}]},
            {
                "id": "m_assistant",
                "role": "assistant",
                "info": {"id": "m_assistant"},
                "metadata": {"usage": {"input_tokens": 10}},
                "parts": [{"type": "reasoning"}, {"type": "tool"}],
            },
        ]


@pytest.mark.anyio
async def test_sync_session_uses_sdk_boundary_and_caches_results() -> None:
    ctx = SyncContext()
    sdk = _FakeSDK()

    await ctx.sync_session("session_1", sdk, force=True)
    messages = ctx.get_messages("session_1")

    assert [msg["role"] for msg in messages] == ["user", "assistant"]
    assert messages[1]["metadata"]["usage"]["input_tokens"] == 10
    assert [part["type"] for part in messages[1]["parts"]] == ["reasoning", "tool"]
    assert sdk.get_session_calls == ["session_1"]
    assert sdk.get_messages_calls == ["session_1"]

    await ctx.sync_session("session_1", sdk, force=False)
    assert sdk.get_session_calls == ["session_1"]
    assert sdk.get_messages_calls == ["session_1"]
