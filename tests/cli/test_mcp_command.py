from __future__ import annotations

from typer.testing import CliRunner

from hotaru.cli.cmd.mcp import app as mcp_app
from hotaru.mcp.mcp import MCPStatusConnected, MCPStatusNeedsAuth


runner = CliRunner()


def test_cli_mcp_status_lists_servers(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    events: list[str] = []

    class _Mcp:
        async def status(self):
            return {
                "demo": MCPStatusNeedsAuth(),
                "local": MCPStatusConnected(),
            }

    class _Ctx:
        def __init__(self) -> None:
            self.mcp = _Mcp()

        async def startup(self) -> None:
            events.append("startup")

        async def shutdown(self) -> None:
            events.append("shutdown")

    monkeypatch.setattr("hotaru.cli.cmd.mcp.AppContext", lambda: _Ctx())

    result = runner.invoke(mcp_app, ["status"])

    assert result.exit_code == 0
    assert "demo: needs_auth" in result.stdout
    assert "local: connected" in result.stdout
    assert events == ["startup", "shutdown"]


def test_cli_mcp_auth_runs_authenticate(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    events: list[str] = []

    class _Mcp:
        async def supports_oauth(self, name: str) -> bool:
            events.append(f"supports:{name}")
            return True

        async def authenticate(self, name: str):
            events.append(f"auth:{name}")
            return MCPStatusConnected()

    class _Ctx:
        def __init__(self) -> None:
            self.mcp = _Mcp()

        async def startup(self) -> None:
            return None

        async def shutdown(self) -> None:
            return None

    monkeypatch.setattr("hotaru.cli.cmd.mcp.AppContext", lambda: _Ctx())

    result = runner.invoke(mcp_app, ["auth", "demo"])

    assert result.exit_code == 0
    assert "demo: connected" in result.stdout
    assert events == ["supports:demo", "auth:demo"]


def test_cli_mcp_logout_runs_remove_auth(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    events: list[str] = []

    class _Mcp:
        async def remove_auth(self, name: str) -> None:
            events.append(name)

        async def status(self):
            return {"demo": MCPStatusConnected()}

    class _Ctx:
        def __init__(self) -> None:
            self.mcp = _Mcp()

        async def startup(self) -> None:
            return None

        async def shutdown(self) -> None:
            return None

    monkeypatch.setattr("hotaru.cli.cmd.mcp.AppContext", lambda: _Ctx())

    result = runner.invoke(mcp_app, ["logout", "demo"])

    assert result.exit_code == 0
    assert "Removed OAuth credentials for demo" in result.stdout
    assert events == ["demo"]


def test_cli_mcp_connect_unknown_server_exits_nonzero(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class _Mcp:
        async def connect(self, name: str, use_oauth: bool = False) -> None:
            raise ValueError(f"MCP server not found: {name}")

    class _Ctx:
        def __init__(self) -> None:
            self.mcp = _Mcp()

        async def startup(self) -> None:
            return None

        async def shutdown(self) -> None:
            return None

    monkeypatch.setattr("hotaru.cli.cmd.mcp.AppContext", lambda: _Ctx())

    result = runner.invoke(mcp_app, ["connect", "missing"])

    assert result.exit_code == 1
    assert "MCP server not found: missing" in result.stdout


def test_cli_mcp_disconnect_unknown_server_exits_nonzero(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class _Mcp:
        async def disconnect(self, name: str) -> None:
            raise ValueError(f"MCP server not found: {name}")

    class _Ctx:
        def __init__(self) -> None:
            self.mcp = _Mcp()

        async def startup(self) -> None:
            return None

        async def shutdown(self) -> None:
            return None

    monkeypatch.setattr("hotaru.cli.cmd.mcp.AppContext", lambda: _Ctx())

    result = runner.invoke(mcp_app, ["disconnect", "missing"])

    assert result.exit_code == 1
    assert "MCP server not found: missing" in result.stdout
