"""MCP OAuth authentication storage.

This module handles persistent storage of OAuth tokens and client information
for MCP servers that require authentication.

Credentials are stored in a JSON file in the user's data directory with
restricted permissions (0o600) for security.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional
from pydantic import BaseModel

from ..core.global_paths import GlobalPath


class OAuthTokens(BaseModel):
    """OAuth token storage.

    Attributes:
        access_token: The access token for API requests
        refresh_token: Optional refresh token for token renewal
        expires_at: Unix timestamp when the token expires
        scope: OAuth scope granted
    """
    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[float] = None
    scope: Optional[str] = None


class ClientInfo(BaseModel):
    """OAuth client information from dynamic registration.

    Attributes:
        client_id: The registered client ID
        client_secret: Optional client secret
        client_id_issued_at: Unix timestamp when client was registered
        client_secret_expires_at: Unix timestamp when secret expires
    """
    client_id: str
    client_secret: Optional[str] = None
    client_id_issued_at: Optional[float] = None
    client_secret_expires_at: Optional[float] = None


class AuthEntry(BaseModel):
    """Complete authentication entry for an MCP server.

    Attributes:
        tokens: OAuth tokens if authenticated
        client_info: Client registration info if dynamically registered
        code_verifier: PKCE code verifier during auth flow
        oauth_state: State parameter during auth flow
        server_url: URL these credentials are for (for validation)
    """
    tokens: Optional[OAuthTokens] = None
    client_info: Optional[ClientInfo] = None
    code_verifier: Optional[str] = None
    oauth_state: Optional[str] = None
    server_url: Optional[str] = None


class McpAuth:
    """MCP OAuth credential storage manager.

    Provides persistent storage for OAuth tokens and client information
    used by MCP servers requiring authentication.
    """

    @classmethod
    def _filepath(cls) -> Path:
        """Get the path to the auth storage file."""
        return GlobalPath.data() / "mcp-auth.json"

    @classmethod
    async def get(cls, mcp_name: str) -> Optional[AuthEntry]:
        """Get authentication entry for an MCP server.

        Args:
            mcp_name: Name of the MCP server

        Returns:
            AuthEntry if found, None otherwise
        """
        data = await cls.all()
        entry_data = data.get(mcp_name)
        if entry_data:
            return AuthEntry.model_validate(entry_data)
        return None

    @classmethod
    async def get_for_url(
        cls,
        mcp_name: str,
        server_url: str
    ) -> Optional[AuthEntry]:
        """Get auth entry and validate it's for the correct URL.

        Returns None if URL has changed (credentials are invalid).

        Args:
            mcp_name: Name of the MCP server
            server_url: Expected server URL

        Returns:
            AuthEntry if valid for URL, None otherwise
        """
        entry = await cls.get(mcp_name)
        if not entry:
            return None

        # If no server_url stored, this is from old version - invalid
        if not entry.server_url:
            return None

        # If URL changed, credentials are invalid
        if entry.server_url != server_url:
            return None

        return entry

    @classmethod
    async def all(cls) -> Dict[str, Any]:
        """Get all stored authentication entries.

        Returns:
            Dictionary of MCP name to auth entry data
        """
        filepath = cls._filepath()
        if not filepath.exists():
            return {}

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}

    @classmethod
    async def set(
        cls,
        mcp_name: str,
        entry: AuthEntry,
        server_url: Optional[str] = None
    ) -> None:
        """Store authentication entry for an MCP server.

        Args:
            mcp_name: Name of the MCP server
            entry: Authentication entry to store
            server_url: Optional server URL to associate with credentials
        """
        filepath = cls._filepath()
        data = await cls.all()

        # Update server_url if provided
        if server_url:
            entry.server_url = server_url

        data[mcp_name] = entry.model_dump(exclude_none=True)

        # Ensure directory exists
        filepath.parent.mkdir(parents=True, exist_ok=True)

        # Write with restricted permissions
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        # Set file permissions (Unix only)
        try:
            os.chmod(filepath, 0o600)
        except (OSError, AttributeError):
            pass  # Windows doesn't support chmod

    @classmethod
    async def remove(cls, mcp_name: str) -> None:
        """Remove authentication entry for an MCP server.

        Args:
            mcp_name: Name of the MCP server
        """
        filepath = cls._filepath()
        data = await cls.all()

        if mcp_name in data:
            del data[mcp_name]

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            try:
                os.chmod(filepath, 0o600)
            except (OSError, AttributeError):
                pass

    @classmethod
    async def update_tokens(
        cls,
        mcp_name: str,
        tokens: OAuthTokens,
        server_url: Optional[str] = None
    ) -> None:
        """Update OAuth tokens for an MCP server.

        Args:
            mcp_name: Name of the MCP server
            tokens: New OAuth tokens
            server_url: Optional server URL to associate
        """
        entry = await cls.get(mcp_name) or AuthEntry()
        entry.tokens = tokens
        await cls.set(mcp_name, entry, server_url)

    @classmethod
    async def update_client_info(
        cls,
        mcp_name: str,
        client_info: ClientInfo,
        server_url: Optional[str] = None
    ) -> None:
        """Update client registration info for an MCP server.

        Args:
            mcp_name: Name of the MCP server
            client_info: Client registration information
            server_url: Optional server URL to associate
        """
        entry = await cls.get(mcp_name) or AuthEntry()
        entry.client_info = client_info
        await cls.set(mcp_name, entry, server_url)

    @classmethod
    async def update_code_verifier(
        cls,
        mcp_name: str,
        code_verifier: str
    ) -> None:
        """Store PKCE code verifier during OAuth flow.

        Args:
            mcp_name: Name of the MCP server
            code_verifier: PKCE code verifier
        """
        entry = await cls.get(mcp_name) or AuthEntry()
        entry.code_verifier = code_verifier
        await cls.set(mcp_name, entry)

    @classmethod
    async def clear_code_verifier(cls, mcp_name: str) -> None:
        """Clear PKCE code verifier after OAuth flow completes.

        Args:
            mcp_name: Name of the MCP server
        """
        entry = await cls.get(mcp_name)
        if entry:
            entry.code_verifier = None
            await cls.set(mcp_name, entry)

    @classmethod
    async def update_oauth_state(
        cls,
        mcp_name: str,
        oauth_state: str
    ) -> None:
        """Store OAuth state parameter during auth flow.

        Args:
            mcp_name: Name of the MCP server
            oauth_state: OAuth state parameter
        """
        entry = await cls.get(mcp_name) or AuthEntry()
        entry.oauth_state = oauth_state
        await cls.set(mcp_name, entry)

    @classmethod
    async def get_oauth_state(cls, mcp_name: str) -> Optional[str]:
        """Get stored OAuth state parameter.

        Args:
            mcp_name: Name of the MCP server

        Returns:
            OAuth state if stored, None otherwise
        """
        entry = await cls.get(mcp_name)
        return entry.oauth_state if entry else None

    @classmethod
    async def clear_oauth_state(cls, mcp_name: str) -> None:
        """Clear OAuth state after auth flow completes.

        Args:
            mcp_name: Name of the MCP server
        """
        entry = await cls.get(mcp_name)
        if entry:
            entry.oauth_state = None
            await cls.set(mcp_name, entry)

    @classmethod
    async def is_token_expired(cls, mcp_name: str) -> Optional[bool]:
        """Check if stored tokens are expired.

        Args:
            mcp_name: Name of the MCP server

        Returns:
            None if no tokens exist
            False if no expiry or not expired
            True if expired
        """
        import time

        entry = await cls.get(mcp_name)
        if not entry or not entry.tokens:
            return None

        if not entry.tokens.expires_at:
            return False

        return entry.tokens.expires_at < time.time()
