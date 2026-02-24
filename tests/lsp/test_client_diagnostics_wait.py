from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from hotaru.core.bus import Bus
from hotaru.lsp.client import DIAGNOSTICS_DEBOUNCE_MS, LSPClient


def _client(tmp_path: Path) -> LSPClient:
    server = SimpleNamespace(process=SimpleNamespace(), initialization={})
    return LSPClient(server_id="pyright", server=server, root=str(tmp_path))


def _diag_payload(client: LSPClient, path: Path) -> dict[str, object]:
    return {
        "uri": client._path_to_uri(str(path)),
        "diagnostics": [],
    }


@pytest.mark.anyio
async def test_wait_for_diagnostics_does_not_use_bus(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    path = tmp_path / "main.py"

    async def fail_publish(cls, event, properties) -> None:
        del cls, event, properties
        raise AssertionError("LSPClient diagnostics should not publish Bus events")

    def fail_subscribe(cls, event, callback):
        del cls, event, callback
        raise AssertionError("LSPClient diagnostics should not subscribe Bus events")

    monkeypatch.setattr(Bus, "publish", classmethod(fail_publish))
    monkeypatch.setattr(Bus, "subscribe", classmethod(fail_subscribe))

    waiter = asyncio.create_task(client.wait_for_diagnostics(str(path), timeout=1.0))
    await asyncio.sleep(0)
    await client._handle_diagnostics(_diag_payload(client, path))
    await asyncio.wait_for(waiter, timeout=1.0)


@pytest.mark.anyio
async def test_wait_for_diagnostics_resets_debounce_on_new_update(tmp_path: Path) -> None:
    client = _client(tmp_path)
    path = tmp_path / "main.py"
    delay = (DIAGNOSTICS_DEBOUNCE_MS - 50) / 1000

    waiter = asyncio.create_task(client.wait_for_diagnostics(str(path), timeout=1.0))
    await asyncio.sleep(0)
    await client._handle_diagnostics(_diag_payload(client, path))
    await asyncio.sleep(delay)
    assert waiter.done() is False

    await client._handle_diagnostics(_diag_payload(client, path))
    await asyncio.sleep(delay)
    assert waiter.done() is False

    await asyncio.wait_for(waiter, timeout=1.0)
