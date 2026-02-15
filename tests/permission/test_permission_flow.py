import asyncio
from types import SimpleNamespace

import pytest

from hotaru.core.bus import Bus
from hotaru.permission import Permission, PermissionReplied, PermissionReply


@pytest.mark.anyio
async def test_permission_request_includes_tool_reference() -> None:
    Permission.reset()

    task = asyncio.create_task(
        Permission.ask(
            session_id="session_test",
            permission="bash",
            patterns=["echo hello"],
            ruleset=[],
            always=["echo *"],
            tool={"message_id": "msg_1", "call_id": "call_1"},
        )
    )

    await asyncio.sleep(0)
    pending = await Permission.list_pending()
    assert len(pending) == 1
    assert pending[0].tool == {"message_id": "msg_1", "call_id": "call_1"}

    await Permission.reply(pending[0].id, PermissionReply.ONCE)
    await task


@pytest.mark.anyio
async def test_permission_replied_event_emitted_for_auto_resolved_requests() -> None:
    Permission.reset()
    replied: list[str] = []

    def on_replied(payload) -> None:  # type: ignore[no-untyped-def]
        replied.append(payload.properties["request_id"])

    unsubscribe = Bus.subscribe(PermissionReplied, on_replied)
    try:
        first = asyncio.create_task(
            Permission.ask(
                session_id="session_test",
                permission="bash",
                patterns=["git status"],
                ruleset=[],
                always=["git *"],
            )
        )
        second = asyncio.create_task(
            Permission.ask(
                session_id="session_test",
                permission="bash",
                patterns=["git diff"],
                ruleset=[],
                always=["git *"],
            )
        )

        await asyncio.sleep(0)
        pending = await Permission.list_pending()
        assert len(pending) == 2
        first_id = next(item.id for item in pending if item.patterns == ["git status"])

        await Permission.reply(first_id, PermissionReply.ALWAYS)
        await first
        await second

        assert set(replied) == {item.id for item in pending}
    finally:
        unsubscribe()


@pytest.mark.anyio
async def test_project_scope_shares_always_approvals_between_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Permission.reset()

    class _Config:
        permission_memory_scope = "project"

    async def fake_config_get(cls):  # type: ignore[no-untyped-def]
        return _Config()

    async def fake_session_get(cls, _session_id: str):  # type: ignore[no-untyped-def]
        return SimpleNamespace(project_id="project_1")

    monkeypatch.setattr("hotaru.core.config.ConfigManager.get", classmethod(fake_config_get))
    monkeypatch.setattr("hotaru.session.session.Session.get", classmethod(fake_session_get))

    first = asyncio.create_task(
        Permission.ask(
            session_id="session_a",
            permission="bash",
            patterns=["npm run test"],
            ruleset=[],
            always=["npm run *"],
        )
    )
    await asyncio.sleep(0)
    pending = await Permission.list_pending()
    assert len(pending) == 1

    await Permission.reply(pending[0].id, PermissionReply.ALWAYS)
    await first

    await Permission.ask(
        session_id="session_b",
        permission="bash",
        patterns=["npm run lint"],
        ruleset=[],
        always=["npm run *"],
    )
    assert await Permission.list_pending() == []
