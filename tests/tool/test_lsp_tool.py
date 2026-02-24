from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from hotaru.lsp import LSP
from hotaru.tool.lsp import LspParams, lsp_execute
from hotaru.tool.tool import ToolContext
from tests.helpers import fake_app


class _Symbol(BaseModel):
    name: str
    kind: int


def _ctx(tmp_path: Path) -> ToolContext:
    ctx = ToolContext(
        app=fake_app(lsp=LSP()),
        session_id="session_test",
        message_id="message_test",
        agent="build",
        cwd=str(tmp_path),
        worktree=str(tmp_path),
    )

    async def fake_ask(*, permission, patterns, always=None, metadata=None) -> None:
        del permission, patterns, always, metadata

    ctx.ask = fake_ask  # type: ignore[method-assign]
    return ctx


@pytest.mark.anyio
async def test_lsp_tool_go_to_implementation_branch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "main.py"
    file_path.write_text("print('x')\n", encoding="utf-8")

    async def fake_has_clients(cls, file: str) -> bool:
        del cls
        assert file == str(file_path)
        return True

    async def fake_touch_file(cls, file: str, wait_for_diagnostics: bool = False) -> int:
        del cls
        assert file == str(file_path)
        assert wait_for_diagnostics is True
        return 1

    async def fake_implementation(cls, file: str, line: int, character: int):
        del cls
        assert file == str(file_path)
        assert (line, character) == (1, 2)
        return [{"uri": "file:///impl.py"}]

    monkeypatch.setattr(LSP, "has_clients", classmethod(fake_has_clients))
    monkeypatch.setattr(LSP, "touch_file", classmethod(fake_touch_file))
    monkeypatch.setattr(LSP, "implementation", classmethod(fake_implementation))

    result = await lsp_execute(
        LspParams(
            operation="goToImplementation",
            filePath=str(file_path),
            line=2,
            character=3,
        ),
        _ctx(tmp_path),
    )

    assert json.loads(result.output) == [{"uri": "file:///impl.py"}]


@pytest.mark.anyio
async def test_lsp_tool_workspace_symbol_outputs_json_for_pydantic_objects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "main.py"
    file_path.write_text("print('x')\n", encoding="utf-8")

    async def fake_has_clients(cls, _file: str) -> bool:
        del cls
        return True

    async def fake_touch_file(cls, _file: str, wait_for_diagnostics: bool = False) -> int:
        del cls
        assert wait_for_diagnostics is True
        return 1

    async def fake_workspace_symbol(cls, query: str):
        del cls
        assert query == ""
        return [_Symbol(name="foo", kind=12)]

    monkeypatch.setattr(LSP, "has_clients", classmethod(fake_has_clients))
    monkeypatch.setattr(LSP, "touch_file", classmethod(fake_touch_file))
    monkeypatch.setattr(LSP, "workspace_symbol", classmethod(fake_workspace_symbol))

    result = await lsp_execute(
        LspParams(
            operation="workspaceSymbol",
            filePath=str(file_path),
            line=1,
            character=1,
        ),
        _ctx(tmp_path),
    )

    assert json.loads(result.output) == [{"name": "foo", "kind": 12}]


@pytest.mark.anyio
async def test_lsp_tool_empty_results_use_fixed_message(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "main.py"
    file_path.write_text("print('x')\n", encoding="utf-8")

    async def fake_has_clients(cls, _file: str) -> bool:
        del cls
        return True

    async def fake_touch_file(cls, _file: str, wait_for_diagnostics: bool = False) -> int:
        del cls, wait_for_diagnostics
        return 1

    async def fake_outgoing_calls(cls, _file: str, line: int, character: int):
        del cls
        assert (line, character) == (0, 0)
        return []

    monkeypatch.setattr(LSP, "has_clients", classmethod(fake_has_clients))
    monkeypatch.setattr(LSP, "touch_file", classmethod(fake_touch_file))
    monkeypatch.setattr(LSP, "outgoing_calls", classmethod(fake_outgoing_calls))

    result = await lsp_execute(
        LspParams(
            operation="outgoingCalls",
            filePath=str(file_path),
            line=1,
            character=1,
        ),
        _ctx(tmp_path),
    )

    assert result.output == "No results found for outgoingCalls"
