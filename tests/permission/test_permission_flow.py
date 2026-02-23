import asyncio
from types import SimpleNamespace

import pytest

from hotaru.core.bus import Bus
from hotaru.permission import Permission, PermissionReplied, PermissionReply


@pytest.mark.anyio
async def test_permission_request_includes_tool_reference() -> None:
    permission = Permission()

    task = asyncio.create_task(
        permission.ask(
            session_id="session_test",
            permission="bash",
            patterns=["echo hello"],
            ruleset=[],
            always=["echo *"],
            tool={"message_id": "msg_1", "call_id": "call_1"},
        )
    )

    await asyncio.sleep(0)
    pending = await permission.list_pending()
    assert len(pending) == 1
    assert pending[0].tool == {"message_id": "msg_1", "call_id": "call_1"}

    await permission.reply(pending[0].id, PermissionReply.ONCE)
    await task


@pytest.mark.anyio
async def test_permission_replied_event_emitted_for_auto_resolved_requests() -> None:
    permission = Permission()
    replied: list[str] = []

    def on_replied(payload) -> None:  # type: ignore[no-untyped-def]
        replied.append(payload.properties["request_id"])

    unsubscribe = Bus.subscribe(PermissionReplied, on_replied)
    try:
        first = asyncio.create_task(
            permission.ask(
                session_id="session_test",
                permission="bash",
                patterns=["git status"],
                ruleset=[],
                always=["git *"],
            )
        )
        second = asyncio.create_task(
            permission.ask(
                session_id="session_test",
                permission="bash",
                patterns=["git diff"],
                ruleset=[],
                always=["git *"],
            )
        )

        await asyncio.sleep(0)
        pending = await permission.list_pending()
        assert len(pending) == 2
        first_id = next(item.id for item in pending if item.patterns == ["git status"])

        await permission.reply(first_id, PermissionReply.ALWAYS)
        await first
        await second

        assert set(replied) == {item.id for item in pending}
    finally:
        unsubscribe()


@pytest.mark.anyio
async def test_permission_reply_always_handles_concurrent_pending_updates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    permission = Permission()

    tasks = [
        asyncio.create_task(
            permission.ask(
                session_id="session_test",
                permission="bash",
                patterns=[pattern],
                ruleset=[],
                always=["git *"],
            )
        )
        for pattern in ["git status", "git diff", "git log"]
    ]

    await asyncio.sleep(0)
    pending = await permission.list_pending()
    assert len(pending) == 3

    main_id = pending[0].id
    rest = [item.id for item in pending[1:]]
    assert len(rest) == 2
    hook_id, rival_id = rest

    publish = Bus.publish
    fired = False

    async def fake_publish(cls, event, properties) -> None:  # type: ignore[no-untyped-def]
        nonlocal fired
        if (
            not fired
            and event == PermissionReplied
            and properties.request_id == hook_id
            and properties.reply == PermissionReply.ALWAYS
        ):
            fired = True
            await permission.reply(rival_id, PermissionReply.ALWAYS)
        await publish(event, properties)

    monkeypatch.setattr(Bus, "publish", classmethod(fake_publish))

    await permission.reply(main_id, PermissionReply.ALWAYS)
    await asyncio.gather(*tasks)
    assert await permission.list_pending() == []


@pytest.mark.anyio
async def test_project_scope_shares_always_approvals_between_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    permission = Permission()

    class _Config:
        permission_memory_scope = "project"

    async def fake_config_get(cls):  # type: ignore[no-untyped-def]
        return _Config()

    async def fake_session_get(cls, _session_id: str):  # type: ignore[no-untyped-def]
        return SimpleNamespace(project_id="project_1")

    monkeypatch.setattr("hotaru.core.config.ConfigManager.get", classmethod(fake_config_get))
    monkeypatch.setattr("hotaru.session.session.Session.get", classmethod(fake_session_get))

    first = asyncio.create_task(
        permission.ask(
            session_id="session_a",
            permission="bash",
            patterns=["npm run test"],
            ruleset=[],
            always=["npm run *"],
        )
    )
    await asyncio.sleep(0)
    pending = await permission.list_pending()
    assert len(pending) == 1

    await permission.reply(pending[0].id, PermissionReply.ALWAYS)
    await first

    await permission.ask(
        session_id="session_b",
        permission="bash",
        patterns=["npm run lint"],
        ruleset=[],
        always=["npm run *"],
    )
    assert await permission.list_pending() == []
