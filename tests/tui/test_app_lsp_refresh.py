import asyncio

import pytest

from hotaru.core.bus import Bus
from hotaru.lsp import LSP
from hotaru.lsp.lsp import LSPUpdated, LSPUpdatedProps
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
