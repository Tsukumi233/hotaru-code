from pathlib import Path

import pytest

from hotaru.lsp import LSP
from hotaru.lsp.client import LSPDiagnostic
from hotaru.tool.edit import EditParams, edit_execute
from hotaru.tool.tool import ToolContext
from hotaru.tool.write import WriteParams, write_execute
from tests.helpers import fake_app


def _diagnostic(message: str) -> LSPDiagnostic:
    return LSPDiagnostic.model_validate(
        {
            "range": {
                "start": {"line": 0, "character": 0},
                "end": {"line": 0, "character": 1},
            },
            "message": message,
            "severity": 1,
            "source": "pyright",
        }
    )


def _tool_context(tmp_path: Path) -> ToolContext:
    ctx = ToolContext(
        app=fake_app(lsp=LSP()),
        session_id="session_test",
        message_id="message_test",
        agent="build",
        extra={"cwd": str(tmp_path), "worktree": str(tmp_path)},
    )

    async def fake_ask(*, permission, patterns, always=None, metadata=None) -> None:
        return None

    ctx.ask = fake_ask  # type: ignore[method-assign]
    return ctx


@pytest.mark.anyio
async def test_write_tool_appends_lsp_feedback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    filepath = tmp_path / "broken.py"
    other_path = tmp_path / "other.py"
    touched: list[tuple[str, bool]] = []

    async def fake_touch_file(cls, file: str, wait_for_diagnostics: bool = False) -> int:
        touched.append((file, wait_for_diagnostics))
        return 1

    async def fake_diagnostics(cls):
        return {
            str(filepath): [_diagnostic("Syntax error")],
            str(other_path): [_diagnostic("Project error")],
        }

    async def fake_has_clients(cls, file: str) -> bool:
        return True

    monkeypatch.setattr(LSP, "has_clients", classmethod(fake_has_clients))
    monkeypatch.setattr(LSP, "touch_file", classmethod(fake_touch_file))
    monkeypatch.setattr(LSP, "diagnostics", classmethod(fake_diagnostics))

    result = await write_execute(
        WriteParams(file_path=str(filepath), content="def broken(\n"),
        _tool_context(tmp_path),
    )

    assert touched == [(str(filepath), True)]
    assert "Wrote file successfully." in result.output
    assert "LSP errors detected in this file, please fix:" in result.output
    assert "LSP errors detected in other files:" in result.output
    assert "ERROR [1:1] Syntax error" in result.output
    assert "ERROR [1:1] Project error" in result.output
    assert result.metadata["diagnostics"][str(filepath)][0].message == "Syntax error"


@pytest.mark.anyio
async def test_edit_tool_appends_lsp_feedback_for_existing_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    filepath = tmp_path / "edit_me.py"
    other_path = tmp_path / "other.py"
    filepath.write_text("x = 1\n", encoding="utf-8")
    touched: list[tuple[str, bool]] = []

    async def fake_touch_file(cls, file: str, wait_for_diagnostics: bool = False) -> int:
        touched.append((file, wait_for_diagnostics))
        return 1

    async def fake_diagnostics(cls):
        return {
            str(filepath): [_diagnostic("Assignment expected")],
            str(other_path): [_diagnostic("Unrelated error")],
        }

    async def fake_has_clients(cls, file: str) -> bool:
        return True

    monkeypatch.setattr(LSP, "has_clients", classmethod(fake_has_clients))
    monkeypatch.setattr(LSP, "touch_file", classmethod(fake_touch_file))
    monkeypatch.setattr(LSP, "diagnostics", classmethod(fake_diagnostics))

    result = await edit_execute(
        EditParams(
            file_path=str(filepath),
            old_string="x = 1\n",
            new_string="x =\n",
        ),
        _tool_context(tmp_path),
    )

    assert touched == [(str(filepath), True)]
    assert "Edit applied successfully." in result.output
    assert "LSP errors detected in this file, please fix:" in result.output
    assert "LSP errors detected in other files:" not in result.output
    assert "ERROR [1:1] Assignment expected" in result.output
    assert result.metadata["diagnostics"][str(filepath)][0].message == "Assignment expected"


@pytest.mark.anyio
async def test_edit_tool_appends_lsp_feedback_when_creating_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    filepath = tmp_path / "new_file.py"
    touched: list[tuple[str, bool]] = []

    async def fake_touch_file(cls, file: str, wait_for_diagnostics: bool = False) -> int:
        touched.append((file, wait_for_diagnostics))
        return 1

    async def fake_diagnostics(cls):
        return {str(filepath): [_diagnostic("Missing expression")]}

    async def fake_has_clients(cls, file: str) -> bool:
        return True

    monkeypatch.setattr(LSP, "has_clients", classmethod(fake_has_clients))
    monkeypatch.setattr(LSP, "touch_file", classmethod(fake_touch_file))
    monkeypatch.setattr(LSP, "diagnostics", classmethod(fake_diagnostics))

    result = await edit_execute(
        EditParams(
            file_path=str(filepath),
            old_string="",
            new_string="x =\n",
        ),
        _tool_context(tmp_path),
    )

    assert touched == [(str(filepath), True)]
    assert filepath.exists()
    assert "LSP errors detected in this file, please fix:" in result.output
    assert "ERROR [1:1] Missing expression" in result.output


@pytest.mark.anyio
async def test_write_tool_reports_when_no_lsp_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    filepath = tmp_path / "no_client.py"

    async def fake_has_clients(cls, file: str) -> bool:
        return False

    async def fake_touch_file(cls, file: str, wait_for_diagnostics: bool = False) -> int:
        return 0

    async def fake_diagnostics(cls):
        return {}

    monkeypatch.setattr(LSP, "has_clients", classmethod(fake_has_clients))
    monkeypatch.setattr(LSP, "touch_file", classmethod(fake_touch_file))
    monkeypatch.setattr(LSP, "diagnostics", classmethod(fake_diagnostics))

    result = await write_execute(
        WriteParams(file_path=str(filepath), content="x = 1\n"),
        _tool_context(tmp_path),
    )

    assert "LSP status: no available server for this file." in result.output


@pytest.mark.anyio
async def test_write_tool_reports_when_diagnostics_not_received(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    filepath = tmp_path / "no_diag.py"

    async def fake_has_clients(cls, file: str) -> bool:
        return True

    async def fake_touch_file(cls, file: str, wait_for_diagnostics: bool = False) -> int:
        return 1

    async def fake_diagnostics(cls):
        return {}

    monkeypatch.setattr(LSP, "has_clients", classmethod(fake_has_clients))
    monkeypatch.setattr(LSP, "touch_file", classmethod(fake_touch_file))
    monkeypatch.setattr(LSP, "diagnostics", classmethod(fake_diagnostics))

    result = await write_execute(
        WriteParams(file_path=str(filepath), content="x = 1\n"),
        _tool_context(tmp_path),
    )

    assert "LSP status: diagnostics not received in time." in result.output


@pytest.mark.anyio
async def test_write_tool_reports_when_lsp_server_fails_to_start(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    filepath = tmp_path / "start_fail.py"

    async def fake_has_clients(cls, file: str) -> bool:
        return True

    async def fake_touch_file(cls, file: str, wait_for_diagnostics: bool = False) -> int:
        return 0

    async def fake_diagnostics(cls):
        return {}

    monkeypatch.setattr(LSP, "has_clients", classmethod(fake_has_clients))
    monkeypatch.setattr(LSP, "touch_file", classmethod(fake_touch_file))
    monkeypatch.setattr(LSP, "diagnostics", classmethod(fake_diagnostics))

    result = await write_execute(
        WriteParams(file_path=str(filepath), content="x = 1\n"),
        _tool_context(tmp_path),
    )

    assert "LSP status: failed to start language server for this file." in result.output


@pytest.mark.anyio
async def test_write_tool_reports_when_lsp_collection_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    filepath = tmp_path / "lsp_fail.py"

    async def fake_has_clients(cls, file: str) -> bool:
        return True

    async def fake_touch_file(cls, file: str, wait_for_diagnostics: bool = False) -> int:
        del cls, file, wait_for_diagnostics
        raise RuntimeError("boom")

    monkeypatch.setattr(LSP, "has_clients", classmethod(fake_has_clients))
    monkeypatch.setattr(LSP, "touch_file", classmethod(fake_touch_file))

    result = await write_execute(
        WriteParams(file_path=str(filepath), content="x = 1\n"),
        _tool_context(tmp_path),
    )

    assert "LSP status: diagnostics unavailable (boom)." in result.output
