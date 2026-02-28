import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest

import hotaru.mcp.mcp as mcp_module
from hotaru.mcp.mcp import MCP, MCPAuthError, _auth_http_error


@pytest.mark.anyio
async def test_remote_unauthorized_maps_to_needs_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mcp = MCP()

    async def fail_connect(self, url: str, headers=None, oauth_auth=None) -> None:
        raise MCPAuthError(
            status_code=401,
            error_code="unauthorized",
            detail="Your client_id is unauthorized",
        )

    monkeypatch.setattr(mcp_module.MCPClient, "connect_remote", fail_connect)

    result = await mcp._create_remote_client(
        "demo",
        {"type": "remote", "url": "https://example.com"},
    )

    assert result["client"] is None
    assert result["status"].status == "needs_auth"


@pytest.mark.anyio
@pytest.mark.parametrize("code", ["invalid_client", "needs_registration"])
async def test_remote_registration_errors_map_to_registration_status(
    monkeypatch: pytest.MonkeyPatch,
    code: str,
) -> None:
    mcp = MCP()

    async def fail_connect(self, url: str, headers=None, oauth_auth=None) -> None:
        raise MCPAuthError(status_code=401, error_code=code)

    monkeypatch.setattr(mcp_module.MCPClient, "connect_remote", fail_connect)

    result = await mcp._create_remote_client(
        "demo",
        {"type": "remote", "url": "https://example.com"},
    )

    assert result["client"] is None
    assert result["status"].status == "needs_client_registration"


@pytest.mark.anyio
async def test_remote_plain_message_no_longer_uses_string_matching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mcp = MCP()

    async def fail_connect(self, url: str, headers=None, oauth_auth=None) -> None:
        raise RuntimeError("Your client_id is unauthorized")

    monkeypatch.setattr(mcp_module.MCPClient, "connect_remote", fail_connect)

    result = await mcp._create_remote_client(
        "demo",
        {"type": "remote", "url": "https://example.com"},
    )

    assert result["client"] is None
    assert result["status"].status == "failed"


@pytest.mark.anyio
async def test_remote_connect_uses_oauth_provider_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mcp = MCP()
    captured: dict[str, object] = {}

    async def fake_connect(self, url: str, headers=None, oauth_auth=None) -> None:
        captured["url"] = url
        captured["headers"] = headers
        captured["oauth_auth"] = oauth_auth
        self._session = object()

    async def fake_list_tools(self):
        return []

    monkeypatch.setattr(mcp_module.MCPClient, "connect_remote", fake_connect)
    monkeypatch.setattr(mcp_module.MCPClient, "list_tools", fake_list_tools)

    result = await mcp._create_remote_client(
        "demo",
        {"type": "remote", "url": "https://example.com", "oauth": {}},
        use_oauth=True,
    )

    assert result["client"] is not None
    assert result["status"].status == "connected"
    assert captured["url"] == "https://example.com"
    assert captured["oauth_auth"] is not None


@pytest.mark.anyio
async def test_remote_cancelled_error_maps_to_failed_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mcp = MCP()

    async def fail_connect(self, url: str, headers=None, oauth_auth=None) -> None:
        raise asyncio.CancelledError("cancelled by internal transport scope")

    monkeypatch.setattr(mcp_module.MCPClient, "connect_remote", fail_connect)

    result = await mcp._create_remote_client(
        "demo",
        {"type": "remote", "url": "https://example.com"},
    )

    assert result["client"] is None
    assert result["status"].status == "failed"


@pytest.mark.anyio
async def test_remote_list_tools_cancelled_error_maps_to_failed_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mcp = MCP()

    async def fake_connect(self, url: str, headers=None, oauth_auth=None) -> None:
        self._session = object()

    async def fail_list_tools(self):
        raise asyncio.CancelledError("cancelled while listing tools")

    monkeypatch.setattr(mcp_module.MCPClient, "connect_remote", fake_connect)
    monkeypatch.setattr(mcp_module.MCPClient, "list_tools", fail_list_tools)

    result = await mcp._create_remote_client(
        "demo",
        {"type": "remote", "url": "https://example.com"},
    )

    assert result["client"] is None
    assert result["status"].status == "failed"


@pytest.mark.anyio
async def test_remote_external_cancelled_error_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mcp = MCP()

    async def fail_connect(self, url: str, headers=None, oauth_auth=None) -> None:
        task = asyncio.current_task()
        assert task is not None
        task.cancel()
        await asyncio.sleep(0)

    monkeypatch.setattr(mcp_module.MCPClient, "connect_remote", fail_connect)

    task = asyncio.create_task(
        mcp._create_remote_client(
            "demo",
            {"type": "remote", "url": "https://example.com"},
        )
    )
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.anyio
async def test_connect_unknown_mcp_raises_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mcp = MCP()

    async def fake_get_config():
        return SimpleNamespace(mcp={})

    monkeypatch.setattr(mcp_module.ConfigManager, "get", fake_get_config)

    with pytest.raises(ValueError, match="MCP server not found: missing"):
        await mcp.connect("missing")


@pytest.mark.anyio
async def test_disconnect_unknown_mcp_raises_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mcp = MCP()

    async def fake_get_config():
        return SimpleNamespace(mcp={})

    monkeypatch.setattr(mcp_module.ConfigManager, "get", fake_get_config)

    with pytest.raises(ValueError, match="MCP server not found: missing"):
        await mcp.disconnect("missing")


@pytest.mark.anyio
async def test_start_auth_concurrent_calls_share_single_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mcp = MCP()
    calls = 0
    gate = asyncio.Event()

    async def fake_get_config():
        return SimpleNamespace(mcp={"demo": {"type": "remote", "url": "https://example.com", "oauth": {}}})

    async def fake_ensure_running():
        return None

    async def fake_update_state(name: str, state: str):
        return None

    @asynccontextmanager
    async def fake_streamable_http_client(url: str, http_client=None):
        await gate.wait()
        yield None

    def fake_create_oauth_provider(
        mcp_name: str,
        server_url: str,
        config,
        redirect_handler,
        callback_handler,
    ):
        nonlocal calls
        calls += 1
        asyncio.get_running_loop().create_task(redirect_handler("https://example.com/oauth?state=abc"))
        return lambda request: request

    monkeypatch.setattr(mcp_module.ConfigManager, "get", fake_get_config)
    monkeypatch.setattr("hotaru.mcp.oauth_callback.McpOAuthCallback.ensure_running", fake_ensure_running)
    monkeypatch.setattr("hotaru.mcp.oauth_provider.create_oauth_provider", fake_create_oauth_provider)
    monkeypatch.setattr(mcp_module.McpAuth, "update_oauth_state", fake_update_state)
    monkeypatch.setattr("mcp.client.streamable_http.streamable_http_client", fake_streamable_http_client)

    first, second = await asyncio.gather(
        mcp.start_auth("demo"),
        mcp.start_auth("demo"),
    )

    assert first["authorization_url"] == "https://example.com/oauth?state=abc"
    assert second["authorization_url"] == "https://example.com/oauth?state=abc"
    assert calls == 1

    await mcp._clear_pending_auth("demo", cancel_task=True)
    gate.set()


def test_auth_http_error_uses_structured_code_not_description_text() -> None:
    request = httpx.Request("POST", "https://example.com")
    response = httpx.Response(
        401,
        request=request,
        headers={"content-type": "application/json"},
        json={
            "error": "unauthorized",
            "error_description": "Your client_id is unauthorized",
        },
    )
    error = httpx.HTTPStatusError("unauthorized", request=request, response=response)

    auth = _auth_http_error(error)

    assert auth is not None
    assert auth.status_code == 401
    assert auth.error_code == "unauthorized"


def test_auth_http_error_parses_registration_code() -> None:
    request = httpx.Request("POST", "https://example.com")
    response = httpx.Response(
        403,
        request=request,
        headers={"content-type": "application/json"},
        json={"error": {"code": "invalid_client"}},
    )
    error = httpx.HTTPStatusError("forbidden", request=request, response=response)

    auth = _auth_http_error(error)

    assert auth is not None
    assert auth.status_code == 403
    assert auth.error_code == "invalid_client"
