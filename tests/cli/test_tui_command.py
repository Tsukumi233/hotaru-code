from __future__ import annotations

import pytest

from hotaru.server.server import DEFAULT_PORT, ServerInfo


@pytest.mark.anyio
async def test_serve_tui_starts_and_stops_server_when_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hotaru.cli.cmd import tui as tui_module

    events: list[tuple[str, object]] = []

    def fake_info(cls):
        return None

    async def fake_start(cls, host: str = "127.0.0.1", port: int = DEFAULT_PORT):
        events.append(("start", (host, port)))
        return ServerInfo(host=host, port=port)

    async def fake_stop(cls) -> None:
        events.append(("stop", None))

    async def fake_run(**kwargs) -> None:
        events.append(("run", kwargs))

    monkeypatch.setattr("hotaru.cli.cmd.tui.Server.info", classmethod(fake_info))
    monkeypatch.setattr("hotaru.cli.cmd.tui.Server.start", classmethod(fake_start))
    monkeypatch.setattr("hotaru.cli.cmd.tui.Server.stop", classmethod(fake_stop))

    await tui_module.serve_tui(
        model="openai/gpt-5",
        agent="build",
        session_id="session_1",
        continue_session=True,
        prompt="hello",
        run=fake_run,
    )

    assert events == [
        ("start", ("127.0.0.1", DEFAULT_PORT)),
        (
            "run",
            {
                "session_id": "session_1",
                "initial_prompt": "hello",
                "model": "openai/gpt-5",
                "agent": "build",
                "continue_session": True,
            },
        ),
        ("stop", None),
    ]


@pytest.mark.anyio
async def test_serve_tui_reuses_existing_server_without_stopping_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hotaru.cli.cmd import tui as tui_module

    events: list[tuple[str, object]] = []

    def fake_info(cls):
        return ServerInfo(host="127.0.0.1", port=DEFAULT_PORT)

    async def fake_start(cls, host: str = "127.0.0.1", port: int = DEFAULT_PORT):
        events.append(("start", (host, port)))
        return ServerInfo(host=host, port=port)

    async def fake_stop(cls) -> None:
        events.append(("stop", None))

    async def fake_run(**kwargs) -> None:
        events.append(("run", kwargs))

    monkeypatch.setattr("hotaru.cli.cmd.tui.Server.info", classmethod(fake_info))
    monkeypatch.setattr("hotaru.cli.cmd.tui.Server.start", classmethod(fake_start))
    monkeypatch.setattr("hotaru.cli.cmd.tui.Server.stop", classmethod(fake_stop))

    await tui_module.serve_tui(
        model=None,
        agent=None,
        session_id=None,
        continue_session=False,
        prompt=None,
        run=fake_run,
    )

    assert events == [
        (
            "run",
            {
                "session_id": None,
                "initial_prompt": None,
                "model": None,
                "agent": None,
                "continue_session": False,
            },
        ),
    ]
