from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hotaru.cli.main import app


runner = CliRunner()


@pytest.mark.anyio
async def test_collect_lsp_diagnostics_calls_touch_then_fetch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from hotaru.cli.cmd import debug as debug_module

    target = tmp_path / "main.py"
    target.write_text("print('ok')\n", encoding="utf-8")
    events: list[tuple[str, object]] = []

    async def fake_provide(cls, directory: str, fn, init=None):
        del cls, init
        events.append(("directory", directory))
        return await fn()

    async def fake_touch_file(file: str, wait_for_diagnostics: bool = False) -> int:
        events.append(("touch", (file, wait_for_diagnostics)))
        return 1

    async def fake_diagnostics():
        events.append(("diagnostics", None))
        return {str(target): [{"message": "E"}]}

    async def fake_runtime_shutdown() -> None:
        events.append(("shutdown", None))

    async def fake_runtime_startup() -> None:
        return None

    class _Runtime:
        def __init__(self) -> None:
            self.lsp = type("L", (), {"touch_file": staticmethod(fake_touch_file), "diagnostics": staticmethod(fake_diagnostics)})()

        async def startup(self) -> None:
            await fake_runtime_startup()

        async def shutdown(self) -> None:
            await fake_runtime_shutdown()

    async def fake_sleep(seconds: float) -> None:
        events.append(("sleep", seconds))

    monkeypatch.setattr("hotaru.cli.cmd.debug.Instance.provide", classmethod(fake_provide))
    monkeypatch.setattr("hotaru.cli.cmd.debug.AppContext", lambda: _Runtime())
    monkeypatch.setattr("hotaru.cli.cmd.debug.asyncio.sleep", fake_sleep)

    result = await debug_module.collect_lsp_diagnostics(str(target), cwd=str(tmp_path), pause_seconds=0.5)

    assert result == {str(target): [{"message": "E"}]}
    assert events == [
        ("directory", str(tmp_path)),
        ("touch", (str(target), True)),
        ("sleep", 0.5),
        ("diagnostics", None),
        ("shutdown", None),
    ]


def test_cli_debug_lsp_diagnostics_outputs_json(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_collect(file_path: str, cwd: str | None = None, pause_seconds: float = 1.0):
        del file_path, cwd, pause_seconds
        return {"/tmp/a.py": [{"message": "E", "severity": 1}]}

    monkeypatch.setattr("hotaru.cli.cmd.debug.collect_lsp_diagnostics", fake_collect)

    result = runner.invoke(app, ["debug", "lsp", "diagnostics", "a.py"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"/tmp/a.py": [{"message": "E", "severity": 1}]}
