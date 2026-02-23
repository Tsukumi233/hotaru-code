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
