from __future__ import annotations

import pytest

from hotaru.server.server import Server


class _Config:
    def __init__(self, *_args, **_kwargs) -> None:
        return


class _UvicornServer:
    def __init__(self, _config) -> None:
        self.started = False
        self.should_exit = False

    async def serve(self) -> None:
        self.started = True


@pytest.mark.anyio
async def test_start_initializes_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    seen: dict[str, object] = {}

    async def fake_initialize(cls) -> str:
        calls.append("initialize")
        return "/tmp/storage"

    def fake_create_app(
        cls,
        ctx,
        *,
        manage_lifecycle: bool = False,
        access_log: bool = True,
    ):
        seen["ctx"] = ctx
        seen["manage_lifecycle"] = manage_lifecycle
        seen["access_log"] = access_log
        return object()

    monkeypatch.setattr("hotaru.server.server.Storage.initialize", classmethod(fake_initialize))
    monkeypatch.setattr("hotaru.server.server.Server._create_app", classmethod(fake_create_app))
    monkeypatch.setattr("uvicorn.Config", _Config)
    monkeypatch.setattr("uvicorn.Server", _UvicornServer)

    info = await Server.start(host="127.0.0.1", port=4301, access_log=False)
    try:
        assert calls == ["initialize"]
        assert info.host == "127.0.0.1"
        assert info.port == 4301
        assert seen["manage_lifecycle"] is True
        assert seen["access_log"] is False
    finally:
        await Server.stop()
