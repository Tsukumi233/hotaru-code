import asyncio

import pytest

from hotaru.core.bus import Bus
from hotaru.lsp import LSP
from hotaru.lsp.lsp import LSPStatus, LSPUpdated, LSPUpdatedProps
from hotaru.mcp import MCP
from hotaru.tui.app import TuiApp


@pytest.mark.anyio
async def test_lsp_updated_event_triggers_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    app = TuiApp()
    calls: list[str] = []

    async def fake_refresh_lsp_status() -> None:
        calls.append("refresh")

    monkeypatch.setattr(app, "_refresh_lsp_status", fake_refresh_lsp_status)
    app._start_runtime_subscriptions()
    try:
        await Bus.publish(LSPUpdated, LSPUpdatedProps())
        task = app._lsp_refresh_task
        if task is not None:
            await task
    finally:
        await app._stop_runtime_subscriptions()

    assert calls == ["refresh"]


@pytest.mark.anyio
async def test_lsp_refresh_is_coalesced_while_running(monkeypatch: pytest.MonkeyPatch) -> None:
    app = TuiApp()
    started = asyncio.Event()
    release = asyncio.Event()
    refresh_count = 0

    async def fake_refresh_lsp_status() -> None:
        nonlocal refresh_count
        refresh_count += 1
        started.set()
        await release.wait()

    monkeypatch.setattr(app, "_refresh_lsp_status", fake_refresh_lsp_status)
    app._start_runtime_subscriptions()
    try:
        await Bus.publish(LSPUpdated, LSPUpdatedProps())
        await started.wait()

        await Bus.publish(LSPUpdated, LSPUpdatedProps())
        await Bus.publish(LSPUpdated, LSPUpdatedProps())
        await asyncio.sleep(0)
        assert refresh_count == 1

        release.set()
        task = app._lsp_refresh_task
        if task is not None:
            await task

        await Bus.publish(LSPUpdated, LSPUpdatedProps())
        task = app._lsp_refresh_task
        if task is not None:
            await task
        assert refresh_count == 2
    finally:
        await app._stop_runtime_subscriptions()


@pytest.mark.anyio
async def test_on_unmount_unsubscribes_lsp_runtime_listener(monkeypatch: pytest.MonkeyPatch) -> None:
    app = TuiApp()
    calls: list[str] = []

    async def fake_refresh_lsp_status() -> None:
        calls.append("refresh")

    async def fake_mcp_shutdown(cls) -> None:
        del cls

    async def fake_lsp_shutdown(cls) -> None:
        del cls

    monkeypatch.setattr(app, "_refresh_lsp_status", fake_refresh_lsp_status)
    monkeypatch.setattr(MCP, "shutdown", classmethod(fake_mcp_shutdown))
    monkeypatch.setattr(LSP, "shutdown", classmethod(fake_lsp_shutdown))

    app._start_runtime_subscriptions()
    await app.on_unmount()

    await Bus.publish(LSPUpdated, LSPUpdatedProps())
    await asyncio.sleep(0)

    assert calls == []


@pytest.mark.anyio
async def test_refresh_lsp_status_runs_in_instance_context(monkeypatch: pytest.MonkeyPatch) -> None:
    app = TuiApp()
    expected_cwd = app.sdk_ctx.cwd

    async def fake_status(cls):
        del cls
        from hotaru.project.instance import Instance

        # Must be called within the app's working instance context.
        assert Instance.directory() == expected_cwd
        return [
            LSPStatus(
                id="pyright",
                name="pyright",
                root=".",
                status="connected",
            )
        ]

    monkeypatch.setattr(LSP, "status", classmethod(fake_status))

    await app._refresh_lsp_status()

    assert len(app.sync_ctx.data.lsp) == 1
    assert app.sync_ctx.data.lsp[0]["id"] == "pyright"


@pytest.mark.anyio
async def test_server_connection_events_notify_users(monkeypatch: pytest.MonkeyPatch) -> None:
    app = TuiApp()
    notices: list[tuple[str, str]] = []

    def fake_notify(message: str, *, severity: str = "information", **_kwargs) -> None:
        notices.append((message, severity))

    monkeypatch.setattr(app, "notify", fake_notify)

    app._start_runtime_subscriptions()
    try:
        app.sdk_ctx.emit_event("server.connection", {"state": "retrying", "attempt": 1, "delay": 0.25})
        app.sdk_ctx.emit_event("server.connection", {"state": "retrying", "attempt": 2, "delay": 0.5})
        app.sdk_ctx.emit_event("server.connection", {"state": "connected"})
        app.sdk_ctx.emit_event("server.connection", {"state": "exhausted", "attempt": 50})
    finally:
        await app._stop_runtime_subscriptions()

    assert notices == [
        ("Server connection lost. Retrying in 0.25s.", "warning"),
        ("Server connection restored.", "information"),
        ("Server unavailable after 50 retries.", "error"),
    ]
