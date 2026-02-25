"""MCP OAuth provider implementation.

Provides TokenStorage and OAuth helper functions for authenticating with remote MCP servers.

The Python MCP SDK uses a different OAuth API than the TypeScript SDK:
- TokenStorage protocol for persisting tokens and client info
- redirect_handler / callback_handler callbacks
- OAuthClientProvider wraps httpx.Auth
"""

import time
from typing import Any, Callable, Coroutine, Dict, Optional, Tuple

from pydantic import AnyUrl

from ..util.log import Log
from .auth import McpAuth, OAuthTokens, ClientInfo

log = Log.create({"service": "mcp.oauth"})

OAUTH_CALLBACK_PORT = 19876
OAUTH_CALLBACK_PATH = "/mcp/oauth/callback"


class McpOAuthConfig:
    """OAuth configuration from MCP server config."""

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        scope: Optional[str] = None,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.scope = scope


class McpTokenStorage:
    """TokenStorage implementation backed by McpAuth persistent storage.

    Implements the mcp.client.auth.TokenStorage protocol, storing tokens
    and client info via the McpAuth JSON file store.
    """

    def __init__(
        self,
        mcp_name: str,
        server_url: str,
        config: Optional[McpOAuthConfig] = None,
    ):
        self.mcp_name = mcp_name
        self.server_url = server_url
        self.config = config or McpOAuthConfig()

    async def get_tokens(self):
        """Retrieve stored OAuth tokens."""
        from mcp.shared.auth import OAuthToken

        entry = await McpAuth.get_for_url(self.mcp_name, self.server_url)
        if not entry or not entry.tokens:
            return None

        return OAuthToken(
            access_token=entry.tokens.access_token,
            token_type="Bearer",
            refresh_token=entry.tokens.refresh_token,
            expires_in=(
                max(0, int(entry.tokens.expires_at - time.time()))
                if entry.tokens.expires_at
                else None
            ),
            scope=entry.tokens.scope,
        )

    async def set_tokens(self, tokens) -> None:
        """Store OAuth tokens."""
        await McpAuth.update_tokens(
            self.mcp_name,
            OAuthTokens(
                access_token=tokens.access_token,
                refresh_token=getattr(tokens, "refresh_token", None),
                expires_at=(
                    time.time() + tokens.expires_in
                    if getattr(tokens, "expires_in", None)
                    else None
                ),
                scope=getattr(tokens, "scope", None),
            ),
            self.server_url,
        )
        log.info("saved oauth tokens", {"mcp_name": self.mcp_name})

    async def get_client_info(self):
        """Retrieve stored client information."""
        from mcp.shared.auth import OAuthClientInformationFull

        # Check pre-registered config first
        if self.config.client_id:
            return OAuthClientInformationFull(
                redirect_uris=None,
                client_id=self.config.client_id,
                client_secret=self.config.client_secret,
            )

        # Check stored from dynamic registration
        entry = await McpAuth.get_for_url(self.mcp_name, self.server_url)
        if entry and entry.client_info:
            # Check if client secret has expired
            if entry.client_info.client_secret_expires_at:
                if entry.client_info.client_secret_expires_at < time.time():
                    log.info("client secret expired, need to re-register", {
                        "mcp_name": self.mcp_name,
                    })
                    return None
            return OAuthClientInformationFull(
                redirect_uris=None,
                client_id=entry.client_info.client_id,
                client_secret=entry.client_info.client_secret,
            )

        return None

    async def set_client_info(self, info) -> None:
        """Store dynamically registered client information."""
        await McpAuth.update_client_info(
            self.mcp_name,
            ClientInfo(
                client_id=info.client_id,
                client_secret=getattr(info, "client_secret", None),
                client_id_issued_at=getattr(info, "client_id_issued_at", None),
                client_secret_expires_at=getattr(info, "client_secret_expires_at", None),
            ),
            self.server_url,
        )
        log.info("saved dynamically registered client", {
            "mcp_name": self.mcp_name,
            "client_id": info.client_id,
        })


def create_oauth_client_metadata(config: Optional[McpOAuthConfig] = None):
    """Create OAuthClientMetadata for hotaru-code.

    Args:
        config: Optional OAuth configuration with client_secret

    Returns:
        OAuthClientMetadata instance
    """
    from mcp.shared.auth import OAuthClientMetadata

    return OAuthClientMetadata(
        redirect_uris=[AnyUrl(f"http://127.0.0.1:{OAUTH_CALLBACK_PORT}{OAUTH_CALLBACK_PATH}")],
        client_name="hotaru-code",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method=(
            "client_secret_post"
            if config and config.client_secret
            else "none"
        ),
    )


def create_oauth_provider(
    mcp_name: str,
    server_url: str,
    config: Optional[McpOAuthConfig] = None,
    redirect_handler: Optional[Callable[[str], Coroutine]] = None,
    callback_handler: Optional[Callable[[], Coroutine[Any, Any, Tuple[str, Optional[str]]]]] = None,
):
    """Create an OAuthClientProvider for an MCP server.

    Args:
        mcp_name: Name of the MCP server
        server_url: URL of the remote MCP server
        config: Optional OAuth configuration
        redirect_handler: Async function called with authorization URL
        callback_handler: Async function that returns (code, state) from callback

    Returns:
        OAuthClientProvider instance configured for this server
    """
    from mcp.client.auth import OAuthClientProvider

    storage = McpTokenStorage(mcp_name, server_url, config)
    metadata = create_oauth_client_metadata(config)

    return OAuthClientProvider(
        server_url=server_url,
        client_metadata=metadata,
        storage=storage,
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )
