import asyncio

import pytest

from hotaru.server.server import Server, ServerInfo


class _FakeServer:
    def __init__(self) -> None:
        self.should_exit = False
        self._checks = 0

    @property
    def checks(self) -> int:
        return self._checks

    @property
    def started(self) -> bool:
        self._checks += 1
        return self._checks < 3


@pytest.mark.anyio
async def test_server_stop_waits_for_shutdown_before_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    sleep = asyncio.sleep

    async def fake_sleep(_delay: float) -> None:
        await sleep(0)

    fake = _FakeServer()
    Server._server = fake
    Server._app = object()  # type: ignore[assignment]
    Server._info = ServerInfo(host="127.0.0.1", port=4096)
    monkeypatch.setattr("hotaru.server.server.asyncio.sleep", fake_sleep)

    await Server.stop()

    assert fake.should_exit is True
    assert fake.checks >= 3
    assert Server._server is None
    assert Server._app is None
    assert Server.info() is None
