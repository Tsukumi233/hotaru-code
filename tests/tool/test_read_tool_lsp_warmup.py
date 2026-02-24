import asyncio
from pathlib import Path

import pytest

import hotaru.tool.read as read_module
from hotaru.lsp import LSP
from hotaru.tool.read import ReadParams, read_execute
from hotaru.tool.tool import ToolContext
from tests.helpers import fake_app


def _tool_context(tmp_path: Path) -> ToolContext:
    ctx = ToolContext(
        app=fake_app(lsp=LSP()),
        session_id="session_test",
        message_id="message_test",
        agent="build",
        cwd=str(tmp_path),
        worktree=str(tmp_path),
    )

    async def fake_ask(*, permission, patterns, always=None, metadata=None) -> None:
        return None

    ctx.ask = fake_ask  # type: ignore[method-assign]
    return ctx


def _capture_background_tasks(monkeypatch: pytest.MonkeyPatch) -> list[asyncio.Task[None]]:
    tasks: list[asyncio.Task[None]] = []
    original_create_task = asyncio.create_task

    def schedule(coro) -> asyncio.Task[None]:
        task = original_create_task(coro)
        tasks.append(task)
        return task

    monkeypatch.setattr(read_module.asyncio, "create_task", schedule)
    return tasks


@pytest.mark.anyio
async def test_read_text_file_warms_lsp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    filepath = tmp_path / "main.py"
    filepath.write_text("print('ok')\n", encoding="utf-8")

    tasks = _capture_background_tasks(monkeypatch)
    touched: list[tuple[str, bool]] = []

    async def fake_touch_file(cls, file: str, wait_for_diagnostics: bool = False) -> int:
        touched.append((file, wait_for_diagnostics))
        return 0

    monkeypatch.setattr(LSP, "touch_file", classmethod(fake_touch_file))

    result = await read_execute(ReadParams(file_path=str(filepath)), _tool_context(tmp_path))
    await asyncio.gather(*tasks, return_exceptions=True)

    assert "<type>file</type>" in result.output
    assert touched == [(str(filepath), False)]


@pytest.mark.anyio
async def test_read_directory_does_not_warm_lsp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()

    tasks = _capture_background_tasks(monkeypatch)
    touched: list[tuple[str, bool]] = []

    async def fake_touch_file(cls, file: str, wait_for_diagnostics: bool = False) -> int:
        touched.append((file, wait_for_diagnostics))
        return 0

    monkeypatch.setattr(LSP, "touch_file", classmethod(fake_touch_file))

    result = await read_execute(ReadParams(file_path=str(tmp_path / "src")), _tool_context(tmp_path))
    await asyncio.gather(*tasks, return_exceptions=True)

    assert "<type>directory</type>" in result.output
    assert touched == []


@pytest.mark.anyio
async def test_read_image_does_not_warm_lsp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    filepath = tmp_path / "image.png"
    filepath.write_bytes(b"\x89PNG\r\n\x1a\n")

    tasks = _capture_background_tasks(monkeypatch)
    touched: list[tuple[str, bool]] = []

    async def fake_touch_file(cls, file: str, wait_for_diagnostics: bool = False) -> int:
        touched.append((file, wait_for_diagnostics))
        return 0

    monkeypatch.setattr(LSP, "touch_file", classmethod(fake_touch_file))

    result = await read_execute(ReadParams(file_path=str(filepath)), _tool_context(tmp_path))
    await asyncio.gather(*tasks, return_exceptions=True)

    assert "Image read successfully" in result.output
    assert touched == []


@pytest.mark.anyio
async def test_read_binary_file_does_not_warm_lsp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    filepath = tmp_path / "compiled.pyc"
    filepath.write_bytes(b"binary")

    tasks = _capture_background_tasks(monkeypatch)
    touched: list[tuple[str, bool]] = []

    async def fake_touch_file(cls, file: str, wait_for_diagnostics: bool = False) -> int:
        touched.append((file, wait_for_diagnostics))
        return 0

    monkeypatch.setattr(LSP, "touch_file", classmethod(fake_touch_file))

    with pytest.raises(ValueError, match="Cannot read binary file"):
        await read_execute(ReadParams(file_path=str(filepath)), _tool_context(tmp_path))

    await asyncio.gather(*tasks, return_exceptions=True)
    assert touched == []


@pytest.mark.anyio
async def test_read_succeeds_when_lsp_warmup_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    filepath = tmp_path / "broken.py"
    filepath.write_text("x = 1\n", encoding="utf-8")

    tasks = _capture_background_tasks(monkeypatch)

    async def fake_touch_file(cls, file: str, wait_for_diagnostics: bool = False) -> int:
        del cls, file, wait_for_diagnostics
        raise RuntimeError("boom")

    monkeypatch.setattr(LSP, "touch_file", classmethod(fake_touch_file))

    result = await read_execute(ReadParams(file_path=str(filepath)), _tool_context(tmp_path))
    await asyncio.gather(*tasks, return_exceptions=True)

    assert "<type>file</type>" in result.output
