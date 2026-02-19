from __future__ import annotations

import pytest
from typer.testing import CliRunner

from hotaru.cli.main import app
from hotaru.server.server import ServerInfo


runner = CliRunner()


def test_cli_web_command_delegates_to_web_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_web_command(*, host: str, port: int, open_browser: bool) -> None:
        captured["host"] = host
        captured["port"] = port
        captured["open_browser"] = open_browser

    monkeypatch.setattr("hotaru.cli.cmd.web.web_command", fake_web_command)

    result = runner.invoke(app, ["web", "--host", "0.0.0.0", "--port", "5001", "--open"])

    assert result.exit_code == 0
    assert captured == {"host": "0.0.0.0", "port": 5001, "open_browser": True}


@pytest.mark.anyio
async def test_web_runtime_starts_and_stops_server(monkeypatch: pytest.MonkeyPatch) -> None:
    from hotaru.cli.cmd import web as web_module

    events: list[tuple[str, object]] = []
    seen_urls: list[str] = []

    async def fake_start(cls, host: str = "127.0.0.1", port: int = 4096) -> ServerInfo:
        events.append(("start", (host, port)))
        return ServerInfo(host=host, port=port)

    async def fake_stop(cls) -> None:
        events.append(("stop", None))

    async def fake_wait() -> None:
        events.append(("wait", None))

    monkeypatch.setattr("hotaru.cli.cmd.web.Server.start", classmethod(fake_start))
    monkeypatch.setattr("hotaru.cli.cmd.web.Server.stop", classmethod(fake_stop))
    monkeypatch.setattr("hotaru.cli.cmd.web.webbrowser.open", lambda url: seen_urls.append(url))

    await web_module.serve_web(host="127.0.0.1", port=4096, open_browser=True, wait=fake_wait)

    assert events == [
        ("start", ("127.0.0.1", 4096)),
        ("wait", None),
        ("stop", None),
    ]
    assert seen_urls == ["http://127.0.0.1:4096"]
