import asyncio

import pytest

from hotaru.lsp.lsp import LSP


class _FakeClient:
    def __init__(self) -> None:
        self.wait_started = asyncio.Event()
        self.open_observed_wait_started = False

    async def wait_for_diagnostics(self, _path: str, timeout: float = 3.0) -> None:
        del timeout
        self.wait_started.set()
        await asyncio.sleep(0.01)

    async def open_file(self, _path: str) -> None:
        # Yield once so any pre-scheduled wait task can run.
        await asyncio.sleep(0)
        self.open_observed_wait_started = self.wait_started.is_set()
        await asyncio.sleep(0.01)


@pytest.mark.anyio
async def test_touch_file_starts_wait_task_before_open(monkeypatch: pytest.MonkeyPatch) -> None:
    lsp = LSP()
    client = _FakeClient()

    async def fake_get_clients(self, file: str):
        del self, file
        return [client]

    monkeypatch.setattr(LSP, "_get_clients", fake_get_clients)

    count = await lsp.touch_file("example.py", wait_for_diagnostics=True)

    assert count == 1
    assert client.open_observed_wait_started is True
