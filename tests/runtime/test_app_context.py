from __future__ import annotations

from types import SimpleNamespace

import pytest

from hotaru.runtime import AppContext


@pytest.mark.anyio
async def test_startup_fails_fast_for_critical_subsystem() -> None:
    app = AppContext()
    events: list[str] = []

    async def mcp_init() -> None:
        raise RuntimeError("mcp unavailable")

    async def mcp_shutdown() -> None:
        events.append("mcp_shutdown")

    async def lsp_init() -> None:
        events.append("lsp_init")

    async def lsp_shutdown() -> None:
        events.append("lsp_shutdown")

    app.mcp = SimpleNamespace(init=mcp_init, shutdown=mcp_shutdown)
    app.lsp = SimpleNamespace(init=lsp_init, shutdown=lsp_shutdown)

    with pytest.raises(RuntimeError, match="critical startup dependency failed: mcp"):
        await app.startup()

    assert app.started is False
    assert app.health["status"] == "failed"
    assert app.subsystem_ready("mcp") is False
    assert app.subsystem_ready("lsp") is False
    assert "lsp_shutdown" in events

    await app.shutdown()


@pytest.mark.anyio
async def test_startup_marks_degraded_for_non_critical_subsystem() -> None:
    app = AppContext()

    async def mcp_init() -> None:
        return None

    async def mcp_shutdown() -> None:
        return None

    async def lsp_init() -> None:
        raise RuntimeError("lsp unavailable")

    async def lsp_shutdown() -> None:
        return None

    app.mcp = SimpleNamespace(init=mcp_init, shutdown=mcp_shutdown)
    app.lsp = SimpleNamespace(init=lsp_init, shutdown=lsp_shutdown)

    await app.startup()
    assert app.started is True
    assert app.health["status"] == "degraded"
    assert app.health["subsystems"]["mcp"]["status"] == "ready"
    assert app.health["subsystems"]["lsp"]["status"] == "failed"
    assert app.subsystem_ready("mcp") is True
    assert app.subsystem_ready("lsp") is False

    await app.shutdown()
