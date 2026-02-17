from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from hotaru.lsp.client import LSPClient


class _FakeProcess:
    def __init__(self) -> None:
        self.terminated = False
        self.killed = False
        self.wait_called = False

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        self.wait_called = True
        return 0

    def kill(self) -> None:
        self.killed = True


class _FakeReader:
    def __init__(self, called: list[str]) -> None:
        self._called = called

    def close(self) -> None:
        self._called.append("reader.close")


class _FakeWriter:
    def __init__(self, called: list[str]) -> None:
        self._called = called

    def close(self) -> None:
        self._called.append("writer.close")


@pytest.mark.anyio
async def test_shutdown_does_not_call_stream_reader_close() -> None:
    calls: list[str] = []
    process = _FakeProcess()
    server = SimpleNamespace(process=process, initialization={})
    client = LSPClient(server_id="fake", server=server, root=".")

    reader_task = asyncio.create_task(asyncio.sleep(0))
    await reader_task

    client._reader_task = reader_task
    client._stream_reader = _FakeReader(calls)
    client._stream_writer = _FakeWriter(calls)

    await client.shutdown()

    assert "reader.close" not in calls
    assert "writer.close" in calls
    assert process.terminated is True
    assert process.wait_called is True
