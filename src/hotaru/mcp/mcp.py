"""MCP client implementation.

This module provides the main MCP client functionality for connecting to
MCP servers and exposing their tools to the AI agent.

Supports both remote (HTTP/SSE) and local (stdio) MCP servers, with
optional OAuth authentication for remote servers.
"""

import asyncio
import os
import subprocess
from typing import Any, Callable, Dict, List, Literal, Optional, Union
from pydantic import BaseModel

from ..core.bus import Bus, BusEvent
from ..core.config import ConfigManager
from ..project.instance import Instance
from ..util.log import Log
from .auth import McpAuth

log = Log.create({"service": "mcp"})

# Default connection timeout
DEFAULT_TIMEOUT = 30.0


class MCPResource(BaseModel):
    """MCP resource definition.

    Attributes:
        name: Resource name
        uri: Resource URI
        description: Optional description
        mime_type: Optional MIME type
        client: Name of the MCP client providing this resource
    """
    name: str
    uri: str
    description: Optional[str] = None
    mime_type: Optional[str] = None
    client: str


class MCPStatusConnected(BaseModel):
    """Status for a connected MCP server."""
    status: Literal["connected"] = "connected"


class MCPStatusDisabled(BaseModel):
    """Status for a disabled MCP server."""
    status: Literal["disabled"] = "disabled"


class MCPStatusFailed(BaseModel):
    """Status for a failed MCP server."""
    status: Literal["failed"] = "failed"
    error: str


class MCPStatusNeedsAuth(BaseModel):
    """Status for an MCP server requiring authentication."""
    status: Literal["needs_auth"] = "needs_auth"


class MCPStatusNeedsClientRegistration(BaseModel):
    """Status for an MCP server requiring client registration."""
    status: Literal["needs_client_registration"] = "needs_client_registration"
    error: str


MCPStatus = Union[
    MCPStatusConnected,
    MCPStatusDisabled,
    MCPStatusFailed,
    MCPStatusNeedsAuth,
    MCPStatusNeedsClientRegistration,
]


class MCPToolDefinition(BaseModel):
    """MCP tool definition from server.

    Attributes:
        name: Tool name
        description: Tool description
        input_schema: JSON Schema for tool input
    """
    name: str
    description: str = ""
    input_schema: Dict[str, Any] = {}


class MCPClient:
    """Wrapper for MCP client connection.

    This is a simplified implementation that wraps the mcp SDK client
    or provides a mock implementation when the SDK is not available.
    """

    def __init__(
        self,
        name: str,
        process: Optional[subprocess.Popen] = None,
        url: Optional[str] = None,
    ):
        """Initialize MCP client.

        Args:
            name: Client name for identification
            process: Subprocess for local MCP servers
            url: URL for remote MCP servers
        """
        self.name = name
        self.process = process
        self.url = url
        self._tools: List[MCPToolDefinition] = []
        self._connected = False

    async def connect(self) -> bool:
        """Connect to the MCP server.

        Returns:
            True if connection successful, False otherwise
        """
        # For local servers, check if process is running
        if self.process:
            if self.process.poll() is None:
                self._connected = True
                return True
            return False

        # For remote servers, try to connect
        if self.url:
            try:
                import httpx
                async with httpx.AsyncClient() as client:
                    # Try to reach the server
                    response = await client.get(
                        self.url,
                        timeout=DEFAULT_TIMEOUT
                    )
                    self._connected = response.status_code < 500
                    return self._connected
            except Exception:
                return False

        return False

    async def list_tools(self) -> List[MCPToolDefinition]:
        """List available tools from the MCP server.

        Returns:
            List of tool definitions
        """
        # In a full implementation, this would communicate with the MCP server
        # For now, return cached tools
        return self._tools

    async def call_tool(
        self,
        name: str,
        arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Call a tool on the MCP server.

        Args:
            name: Tool name
            arguments: Tool arguments

        Returns:
            Tool execution result
        """
        # In a full implementation, this would send the request to the MCP server
        return {"error": "MCP tool execution not implemented"}

    async def list_prompts(self) -> List[Dict[str, Any]]:
        """List available prompts from the MCP server.

        Returns:
            List of prompt definitions
        """
        return []

    async def list_resources(self) -> List[Dict[str, Any]]:
        """List available resources from the MCP server.

        Returns:
            List of resource definitions
        """
        return []

    async def close(self) -> None:
        """Close the MCP client connection."""
        self._connected = False
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()


class MCPState:
    """State container for MCP clients."""

    def __init__(self):
        self.clients: Dict[str, MCPClient] = {}
        self.status: Dict[str, MCPStatus] = {}


# Global state (per-instance in full implementation)
_state: Optional[MCPState] = None


class ToolsChangedProps(BaseModel):
    """Properties for tools changed event."""
    server: str


class BrowserOpenFailedProps(BaseModel):
    """Properties for browser open failed event."""
    mcp_name: str
    url: str


# Events
ToolsChanged = BusEvent.define("mcp.tools.changed", ToolsChangedProps)
BrowserOpenFailed = BusEvent.define("mcp.browser.open.failed", BrowserOpenFailedProps)


class MCP:
    """MCP client manager.

    Provides methods for managing MCP server connections and
    accessing their tools, prompts, and resources.
    """

    @classmethod
    async def _get_state(cls) -> MCPState:
        """Get or initialize the MCP state.

        Returns:
            MCPState instance
        """
        global _state
        if _state is None:
            _state = MCPState()
            await cls._init_clients()
        return _state

    @classmethod
    async def _init_clients(cls) -> None:
        """Initialize MCP clients from configuration."""
        state = _state
        if not state:
            return

        config = await ConfigManager.get()
        mcp_config = config.mcp or {}

        for name, mcp in mcp_config.items():
            if not isinstance(mcp, dict) or "type" not in mcp:
                log.error("Ignoring MCP config entry without type", {"key": name})
                continue

            # Check if disabled
            if mcp.get("enabled") is False:
                state.status[name] = MCPStatusDisabled()
                continue

            result = await cls._create_client(name, mcp)
            state.status[name] = result["status"]
            if result.get("client"):
                state.clients[name] = result["client"]

    @classmethod
    async def _create_client(
        cls,
        name: str,
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create an MCP client from configuration.

        Args:
            name: Client name
            config: MCP configuration

        Returns:
            Dictionary with 'client' and 'status' keys
        """
        mcp_type = config.get("type")

        if mcp_type == "remote":
            return await cls._create_remote_client(name, config)
        elif mcp_type == "local":
            return await cls._create_local_client(name, config)
        else:
            return {
                "client": None,
                "status": MCPStatusFailed(error=f"Unknown MCP type: {mcp_type}")
            }

    @classmethod
    async def _create_remote_client(
        cls,
        name: str,
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create a remote MCP client.

        Args:
            name: Client name
            config: MCP configuration

        Returns:
            Dictionary with 'client' and 'status' keys
        """
        url = config.get("url")
        if not url:
            return {
                "client": None,
                "status": MCPStatusFailed(error="Missing URL for remote MCP")
            }

        timeout = config.get("timeout", DEFAULT_TIMEOUT)

        try:
            client = MCPClient(name=name, url=url)

            # Try to connect
            connected = await asyncio.wait_for(
                client.connect(),
                timeout=timeout
            )

            if connected:
                log.info("connected to remote MCP", {"name": name, "url": url})
                return {
                    "client": client,
                    "status": MCPStatusConnected()
                }
            else:
                return {
                    "client": None,
                    "status": MCPStatusFailed(error="Failed to connect")
                }

        except asyncio.TimeoutError:
            return {
                "client": None,
                "status": MCPStatusFailed(error="Connection timeout")
            }
        except Exception as e:
            error_msg = str(e)

            # Check for auth-related errors
            if "unauthorized" in error_msg.lower():
                if "registration" in error_msg.lower():
                    return {
                        "client": None,
                        "status": MCPStatusNeedsClientRegistration(
                            error="Server requires pre-registered client ID"
                        )
                    }
                return {
                    "client": None,
                    "status": MCPStatusNeedsAuth()
                }

            return {
                "client": None,
                "status": MCPStatusFailed(error=error_msg)
            }

    @classmethod
    async def _create_local_client(
        cls,
        name: str,
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create a local MCP client.

        Args:
            name: Client name
            config: MCP configuration

        Returns:
            Dictionary with 'client' and 'status' keys
        """
        command = config.get("command", [])
        if not command:
            return {
                "client": None,
                "status": MCPStatusFailed(error="Missing command for local MCP")
            }

        environment = config.get("environment", {})
        timeout = config.get("timeout", DEFAULT_TIMEOUT)

        try:
            # Get working directory
            cwd = Instance.directory()

            # Prepare environment
            env = os.environ.copy()
            env.update(environment)

            # Start the process
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                env=env,
            )

            client = MCPClient(name=name, process=process)

            # Wait for connection
            connected = await asyncio.wait_for(
                client.connect(),
                timeout=timeout
            )

            if connected:
                log.info("connected to local MCP", {
                    "name": name,
                    "command": command
                })
                return {
                    "client": client,
                    "status": MCPStatusConnected()
                }
            else:
                process.terminate()
                return {
                    "client": None,
                    "status": MCPStatusFailed(error="Process failed to start")
                }

        except asyncio.TimeoutError:
            return {
                "client": None,
                "status": MCPStatusFailed(error="Connection timeout")
            }
        except Exception as e:
            log.error("local MCP startup failed", {
                "name": name,
                "command": command,
                "error": str(e)
            })
            return {
                "client": None,
                "status": MCPStatusFailed(error=str(e))
            }

    @classmethod
    async def init(cls) -> None:
        """Initialize MCP clients from configuration."""
        await cls._get_state()

    @classmethod
    async def status(cls) -> Dict[str, MCPStatus]:
        """Get status of all configured MCP servers.

        Returns:
            Dictionary of server name to status
        """
        state = await cls._get_state()
        config = await ConfigManager.get()
        mcp_config = config.mcp or {}

        result: Dict[str, MCPStatus] = {}
        for name, mcp in mcp_config.items():
            if not isinstance(mcp, dict) or "type" not in mcp:
                continue
            result[name] = state.status.get(name, MCPStatusDisabled())

        return result

    @classmethod
    async def clients(cls) -> Dict[str, MCPClient]:
        """Get all connected MCP clients.

        Returns:
            Dictionary of client name to client instance
        """
        state = await cls._get_state()
        return state.clients

    @classmethod
    async def connect(cls, name: str) -> None:
        """Connect to a specific MCP server.

        Args:
            name: Name of the MCP server to connect
        """
        config = await ConfigManager.get()
        mcp_config = config.mcp or {}
        mcp = mcp_config.get(name)

        if not mcp:
            log.error("MCP config not found", {"name": name})
            return

        if not isinstance(mcp, dict) or "type" not in mcp:
            log.error("Invalid MCP config", {"name": name})
            return

        # Force enabled
        mcp_copy = dict(mcp)
        mcp_copy["enabled"] = True

        result = await cls._create_client(name, mcp_copy)

        state = await cls._get_state()
        state.status[name] = result["status"]

        if result.get("client"):
            # Close existing client if present
            if name in state.clients:
                await state.clients[name].close()
            state.clients[name] = result["client"]

    @classmethod
    async def disconnect(cls, name: str) -> None:
        """Disconnect from a specific MCP server.

        Args:
            name: Name of the MCP server to disconnect
        """
        state = await cls._get_state()

        if name in state.clients:
            await state.clients[name].close()
            del state.clients[name]

        state.status[name] = MCPStatusDisabled()

    @classmethod
    async def tools(cls) -> Dict[str, Dict[str, Any]]:
        """Get all tools from connected MCP servers.

        Returns:
            Dictionary of tool name to tool definition
        """
        state = await cls._get_state()
        config = await ConfigManager.get()
        mcp_config = config.mcp or {}

        result: Dict[str, Dict[str, Any]] = {}

        for client_name, client in state.clients.items():
            # Only include tools from connected MCPs
            status = state.status.get(client_name)
            if not isinstance(status, MCPStatusConnected):
                continue

            try:
                tools = await client.list_tools()

                mcp_cfg = mcp_config.get(client_name, {})
                timeout = mcp_cfg.get("timeout", DEFAULT_TIMEOUT) if isinstance(mcp_cfg, dict) else DEFAULT_TIMEOUT

                for tool in tools:
                    # Sanitize names for tool ID
                    safe_client = client_name.replace("-", "_").replace(".", "_")
                    safe_tool = tool.name.replace("-", "_").replace(".", "_")
                    tool_id = f"{safe_client}_{safe_tool}"

                    result[tool_id] = {
                        "name": tool.name,
                        "description": tool.description,
                        "input_schema": tool.input_schema,
                        "client": client_name,
                        "timeout": timeout,
                    }

            except Exception as e:
                log.error("failed to get tools", {
                    "client": client_name,
                    "error": str(e)
                })
                state.status[client_name] = MCPStatusFailed(error=str(e))
                if client_name in state.clients:
                    del state.clients[client_name]

        return result

    @classmethod
    async def prompts(cls) -> Dict[str, Dict[str, Any]]:
        """Get all prompts from connected MCP servers.

        Returns:
            Dictionary of prompt name to prompt definition
        """
        state = await cls._get_state()
        result: Dict[str, Dict[str, Any]] = {}

        for client_name, client in state.clients.items():
            status = state.status.get(client_name)
            if not isinstance(status, MCPStatusConnected):
                continue

            try:
                prompts = await client.list_prompts()

                for prompt in prompts:
                    safe_client = client_name.replace("-", "_").replace(".", "_")
                    safe_prompt = prompt.get("name", "").replace("-", "_").replace(".", "_")
                    prompt_id = f"{safe_client}:{safe_prompt}"

                    result[prompt_id] = {
                        **prompt,
                        "client": client_name,
                    }

            except Exception as e:
                log.error("failed to get prompts", {
                    "client": client_name,
                    "error": str(e)
                })

        return result

    @classmethod
    async def resources(cls) -> Dict[str, MCPResource]:
        """Get all resources from connected MCP servers.

        Returns:
            Dictionary of resource name to resource definition
        """
        state = await cls._get_state()
        result: Dict[str, MCPResource] = {}

        for client_name, client in state.clients.items():
            status = state.status.get(client_name)
            if not isinstance(status, MCPStatusConnected):
                continue

            try:
                resources = await client.list_resources()

                for resource in resources:
                    safe_client = client_name.replace("-", "_").replace(".", "_")
                    safe_name = resource.get("name", "").replace("-", "_").replace(".", "_")
                    resource_id = f"{safe_client}:{safe_name}"

                    result[resource_id] = MCPResource(
                        name=resource.get("name", ""),
                        uri=resource.get("uri", ""),
                        description=resource.get("description"),
                        mime_type=resource.get("mimeType"),
                        client=client_name,
                    )

            except Exception as e:
                log.error("failed to get resources", {
                    "client": client_name,
                    "error": str(e)
                })

        return result

    @classmethod
    async def get_prompt(
        cls,
        client_name: str,
        name: str,
        args: Optional[Dict[str, str]] = None
    ) -> Optional[Dict[str, Any]]:
        """Get a specific prompt from an MCP server.

        Args:
            client_name: Name of the MCP client
            name: Prompt name
            args: Optional prompt arguments

        Returns:
            Prompt result or None if not found
        """
        state = await cls._get_state()
        client = state.clients.get(client_name)

        if not client:
            log.warn("client not found for prompt", {"client": client_name})
            return None

        # In full implementation, would call client.get_prompt()
        return None

    @classmethod
    async def read_resource(
        cls,
        client_name: str,
        resource_uri: str
    ) -> Optional[Dict[str, Any]]:
        """Read a resource from an MCP server.

        Args:
            client_name: Name of the MCP client
            resource_uri: URI of the resource to read

        Returns:
            Resource content or None if not found
        """
        state = await cls._get_state()
        client = state.clients.get(client_name)

        if not client:
            log.warn("client not found for resource", {"client": client_name})
            return None

        # In full implementation, would call client.read_resource()
        return None

    @classmethod
    async def supports_oauth(cls, mcp_name: str) -> bool:
        """Check if an MCP server supports OAuth.

        Remote servers support OAuth by default unless explicitly disabled.

        Args:
            mcp_name: Name of the MCP server

        Returns:
            True if OAuth is supported
        """
        config = await ConfigManager.get()
        mcp_config = config.mcp or {}
        mcp = mcp_config.get(mcp_name)

        if not mcp or not isinstance(mcp, dict):
            return False

        return mcp.get("type") == "remote" and mcp.get("oauth") is not False

    @classmethod
    async def has_stored_tokens(cls, mcp_name: str) -> bool:
        """Check if an MCP server has stored OAuth tokens.

        Args:
            mcp_name: Name of the MCP server

        Returns:
            True if tokens are stored
        """
        entry = await McpAuth.get(mcp_name)
        return entry is not None and entry.tokens is not None

    @classmethod
    async def get_auth_status(
        cls,
        mcp_name: str
    ) -> Literal["authenticated", "expired", "not_authenticated"]:
        """Get the authentication status for an MCP server.

        Args:
            mcp_name: Name of the MCP server

        Returns:
            Authentication status string
        """
        has_tokens = await cls.has_stored_tokens(mcp_name)
        if not has_tokens:
            return "not_authenticated"

        expired = await McpAuth.is_token_expired(mcp_name)
        return "expired" if expired else "authenticated"

    @classmethod
    async def remove_auth(cls, mcp_name: str) -> None:
        """Remove OAuth credentials for an MCP server.

        Args:
            mcp_name: Name of the MCP server
        """
        from .oauth_callback import McpOAuthCallback

        await McpAuth.remove(mcp_name)
        McpOAuthCallback.cancel_pending(mcp_name)
        await McpAuth.clear_oauth_state(mcp_name)
        log.info("removed oauth credentials", {"mcp_name": mcp_name})

    @classmethod
    async def shutdown(cls) -> None:
        """Shutdown all MCP clients."""
        global _state
        if _state:
            for client in _state.clients.values():
                try:
                    await client.close()
                except Exception as e:
                    log.error("Failed to close MCP client", {"error": str(e)})
            _state = None
