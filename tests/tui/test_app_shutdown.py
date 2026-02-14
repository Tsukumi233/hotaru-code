import pytest

from hotaru.lsp import LSP
from hotaru.mcp import MCP
from hotaru.tui.app import TuiApp


@pytest.mark.anyio
async def test_on_unmount_shuts_down_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def fake_mcp_shutdown(cls) -> None:
        calls.append("mcp")

    async def fake_lsp_shutdown(cls) -> None:
        calls.append("lsp")

    monkeypatch.setattr(MCP, "shutdown", classmethod(fake_mcp_shutdown))
    monkeypatch.setattr(LSP, "shutdown", classmethod(fake_lsp_shutdown))

    app = TuiApp()
    await app.on_unmount()

    assert calls == ["mcp", "lsp"]
