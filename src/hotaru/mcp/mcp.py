"""MCP client implementation.

This module provides the main MCP client functionality for connecting to
MCP servers and exposing their tools to the AI agent.

Supports both remote (HTTP/SSE) and local (stdio) MCP servers, with
optional OAuth authentication for remote servers.

Uses the `mcp` Python SDK (ClientSession, transports) for real protocol
communication instead of stubs.
"""

import asyncio
import json
import os
import re
from contextlib import AsyncExitStack
from typing import Any, Dict, List, Literal, Optional, Union
from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel

from ..core.bus import Bus, BusEvent
from ..core.config import ConfigManager
from ..util.log import Log
from .auth import McpAuth

log = Log.create({"service": "mcp"})

# Default connection timeout in seconds
DEFAULT_TIMEOUT = 30.0


class MCPResource(BaseModel):
    """MCP resource definition."""
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


class MCPAuthError(Exception):
    """Structured MCP authentication error from transport layer."""
    def __init__(
        self,
        status_code: int,
        error_code: str = "unauthorized",
        detail: Optional[str] = None,
    ) -> None:
        self.status_code = status_code
        self.error_code = error_code
        self.detail = detail
        message = f"MCP auth error ({status_code}): {error_code}"
        if detail:
            message = f"{message}: {detail}"
        super().__init__(message)


MCPStatus = Union[
    MCPStatusConnected,
    MCPStatusDisabled,
    MCPStatusFailed,
    MCPStatusNeedsAuth,
    MCPStatusNeedsClientRegistration,
]


REGISTRATION_ERROR_CODES = frozenset(
    {
        "invalid_client",
        "needs_registration",
        "needs_client_registration",
        "registration_required",
        "unregistered_client",
    }
)
def _auth_detail(data: Dict[str, Any]) -> Optional[str]:
    for key in ("error_description", "message", "detail", "title"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return None
def _auth_code(data: Dict[str, Any]) -> Optional[str]:
    value = data.get("error")
    if isinstance(value, str) and value:
        return value
    if isinstance(value, dict):
        key = value.get("code")
        if isinstance(key, str) and key:
            return key
        if isinstance(key, int):
            return str(key)
        inner = value.get("error")
        if isinstance(inner, str) and inner:
            return inner

    key = data.get("error_code")
    if isinstance(key, str) and key:
        return key
    if isinstance(key, int):
        return str(key)

    key = data.get("code")
    if isinstance(key, str) and key:
        return key
    if isinstance(key, int):
        return str(key)

    return None
def _auth_http_error(error: Exception) -> Optional[MCPAuthError]:
    try:
        import httpx
    except ImportError:
        return None

    if not isinstance(error, httpx.HTTPStatusError):
        return None

    response = error.response
    status_code = response.status_code
    if status_code not in {401, 403}:
        return None

    data: Dict[str, Any] = {}
    if "json" in response.headers.get("content-type", "").lower():
        try:
            body = response.json()
            if isinstance(body, dict):
                data = body
        except json.JSONDecodeError:
            data = {}
        except ValueError:
            data = {}

    error_code = _auth_code(data) or "unauthorized"
    detail = _auth_detail(data)
    return MCPAuthError(status_code=status_code, error_code=error_code, detail=detail)
def _needs_registration(error_code: str) -> bool:
    return error_code.lower() in REGISTRATION_ERROR_CODES


async def _safe_aclose(stack: "AsyncExitStack") -> None:
    """Close an AsyncExitStack, suppressing cleanup errors from MCP transports.

    The MCP SDK's streamable_http_client uses anyio task groups internally.
    When a connection fails, closing the async context can raise
    BaseExceptionGroup or RuntimeError from cancel scope mismatches.
    These are harmless cleanup artifacts that must not mask the real error.
    """
    try:
        await stack.aclose()
    except BaseException:
        pass


def _is_external_cancellation() -> bool:
    task = asyncio.current_task()
    return task is not None and task.cancelling() > 0


class MCPToolDefinition(BaseModel):
    """MCP tool definition from server."""
    name: str
    description: str = ""
    input_schema: Dict[str, Any] = {}


class MCPClient:
    """Wrapper for a real MCP SDK ClientSession.

    Manages the async context stack for transport + session lifecycle.
    Supports both stdio and remote (StreamableHTTP / SSE) transports.
    """
    def __init__(self, name: str):
        self.name = name
        self._session = None  # mcp.ClientSession
        self._cm_stack: Optional[AsyncExitStack] = None
    async def connect_stdio(
        self,
        command: str,
        args: List[str],
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> None:
        """Connect via stdio transport.

        Args:
            command: Executable command
            args: Command arguments
            cwd: Working directory
            env: Environment variables
        """
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=command,
            args=args,
            cwd=cwd,
            env=env,
        )

        stack = AsyncExitStack()
        read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()

        self._session = session
        self._cm_stack = stack
    async def connect_remote(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        oauth_auth=None,
    ) -> None:
        """Connect via StreamableHTTP, falling back to SSE.

        Args:
            url: Server URL
            headers: Optional HTTP headers
            oauth_auth: Optional httpx.Auth (OAuthClientProvider) for OAuth
        """
        import httpx
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        # Try StreamableHTTP first
        stack = AsyncExitStack()
        try:
            http_client_kwargs: Dict[str, Any] = {}
            if headers:
                http_client_kwargs["headers"] = headers
            if oauth_auth is not None:
                http_client_kwargs["auth"] = oauth_auth
            http_client = await stack.enter_async_context(httpx.AsyncClient(**http_client_kwargs))
            transport_cm = streamable_http_client(url, http_client=http_client)
            read, write, _ = await stack.enter_async_context(transport_cm)
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()

            self._session = session
            self._cm_stack = stack
            return
        except httpx.HTTPStatusError as e:
            await _safe_aclose(stack)
            auth_error = _auth_http_error(e)
            if auth_error:
                raise auth_error from e
        except asyncio.CancelledError as e:
            await _safe_aclose(stack)
            if _is_external_cancellation():
                raise
            raise ConnectionError("MCP transport cancelled") from e
        except BaseExceptionGroup:
            await _safe_aclose(stack)
        except Exception:
            await _safe_aclose(stack)

        # Fallback to SSE
        from mcp.client.sse import sse_client

        stack = AsyncExitStack()
        try:
            transport_cm = sse_client(
                url,
                headers=headers,
                auth=oauth_auth,
            )
            read, write = await stack.enter_async_context(transport_cm)
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()

            self._session = session
            self._cm_stack = stack
        except httpx.HTTPStatusError as e:
            await _safe_aclose(stack)
            auth_error = _auth_http_error(e)
            if auth_error:
                raise auth_error from e
            raise
        except asyncio.CancelledError as e:
            await _safe_aclose(stack)
            if _is_external_cancellation():
                raise
            raise ConnectionError("MCP transport cancelled") from e
        except BaseExceptionGroup as eg:
            await _safe_aclose(stack)
            raise ConnectionError(f"MCP transport failed: {eg}") from eg
        except Exception:
            await _safe_aclose(stack)
            raise

    @property
    def connected(self) -> bool:
        return self._session is not None
    async def list_tools(self) -> List[MCPToolDefinition]:
        """List available tools from the MCP server."""
        if not self._session:
            return []

        result = await self._session.list_tools()
        tools = []
        for t in result.tools:
            tools.append(MCPToolDefinition(
                name=t.name,
                description=t.description or "",
                input_schema=t.inputSchema if isinstance(t.inputSchema, dict) else {},
            ))
        return tools
    async def call_tool(self, name: str, arguments: Dict[str, Any]):
        """Call a tool on the MCP server.

        Args:
            name: Tool name
            arguments: Tool arguments

        Returns:
            CallToolResult from the SDK
        """
        if not self._session:
            raise RuntimeError(f"MCPClient '{self.name}' is not connected")
        return await self._session.call_tool(name, arguments)
    async def list_prompts(self) -> List[Dict[str, Any]]:
        """List available prompts from the MCP server."""
        if not self._session:
            return []

        result = await self._session.list_prompts()
        prompts = []
        for p in result.prompts:
            prompts.append({
                "name": p.name,
                "description": getattr(p, "description", None) or "",
                "arguments": [
                    {"name": a.name, "description": getattr(a, "description", None), "required": getattr(a, "required", False)}
                    for a in (getattr(p, "arguments", None) or [])
                ],
            })
        return prompts
    async def list_resources(self) -> List[Dict[str, Any]]:
        """List available resources from the MCP server."""
        if not self._session:
            return []

        result = await self._session.list_resources()
        resources = []
        for r in result.resources:
            resources.append({
                "name": r.name,
                "uri": str(r.uri),
                "description": getattr(r, "description", None),
                "mimeType": getattr(r, "mimeType", None),
            })
        return resources
    async def get_prompt(self, name: str, args: Optional[Dict[str, str]] = None):
        """Get a specific prompt from the server."""
        if not self._session:
            return None
        return await self._session.get_prompt(name, arguments=args)
    async def read_resource(self, uri: str):
        """Read a resource from the server."""
        if not self._session:
            return None
        return await self._session.read_resource(uri)
    async def close(self) -> None:
        """Close the MCP client connection."""
        if self._cm_stack:
            try:
                await self._cm_stack.aclose()
            except Exception:
                pass
        self._session = None
        self._cm_stack = None


class MCPState:
    """State container for MCP clients."""
    def __init__(self):
        self.clients: Dict[str, MCPClient] = {}
        self.status: Dict[str, MCPStatus] = {}


class PendingAuthFlow:
    """Pending OAuth authorization flow for a single MCP server."""

    def __init__(
        self,
        auth_task: "asyncio.Task[Dict[str, str]]",
        callback_future: "asyncio.Future[tuple[str, str | None]]",
        url_future: "asyncio.Future[str]",
    ) -> None:
        self.auth_task = auth_task
        self.callback_future = callback_future
        self.url_future = url_future

def _sanitize_name(name: str) -> str:
    """Sanitize a name for use in tool/prompt/resource IDs."""
    return re.sub(r"[^a-zA-Z0-9_]", "_", name)


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
def _get_mcp_config_dict(mcp) -> Optional[Dict[str, Any]]:
    """Convert an MCP config entry (Pydantic model or dict) to a dict.

    Returns None if the entry is not a valid MCP config.
    """
    if isinstance(mcp, dict):
        if "type" not in mcp:
            return None
        return mcp
    if hasattr(mcp, "model_dump"):
        d = mcp.model_dump()
        if "type" not in d:
            return None
        return d
    return None


class MCP:
    """MCP client manager.

    Provides methods for managing MCP server connections and
    accessing their tools, prompts, and resources.
    """

    def __init__(self) -> None:
        self._state: Optional[MCPState] = None
        self._init_lock = asyncio.Lock()
        self._pending_auth: Dict[str, PendingAuthFlow] = {}
        self._auth_locks: Dict[str, asyncio.Lock] = {}

    def _auth_lock(self, mcp_name: str) -> asyncio.Lock:
        return self._auth_locks.setdefault(mcp_name, asyncio.Lock())

    async def _clear_pending_auth(self, mcp_name: str, cancel_task: bool = False) -> None:
        flow = self._pending_auth.pop(mcp_name, None)
        if not flow:
            return
        if cancel_task and not flow.auth_task.done():
            flow.auth_task.cancel()
        if not flow.callback_future.done():
            flow.callback_future.cancel()
        if not flow.url_future.done():
            flow.url_future.cancel()

    async def _get_state(self) -> MCPState:
        """Get or initialize the MCP state."""
        if self._state is not None:
            return self._state

        async with self._init_lock:
            # Double-check after acquiring lock
            if self._state is not None:
                return self._state
            self._state = MCPState()
            await self._init_clients()
            return self._state

    async def _init_clients(self) -> None:
        """Initialize MCP clients from configuration."""
        state = self._state
        if not state:
            return

        config = await ConfigManager.get()
        mcp_config = config.mcp or {}

        for name, mcp in mcp_config.items():
            cfg_dict = _get_mcp_config_dict(mcp)
            if cfg_dict is None:
                log.error("Ignoring MCP config entry without type", {"key": name})
                continue

            if cfg_dict.get("enabled") is False:
                state.status[name] = MCPStatusDisabled()
                continue

            # Streamable HTTP transport cleanup must run in the same task as setup.
            # Initialize sequentially to keep client lifecycle task-affine.
            await self._init_single_client(name, cfg_dict)

    async def _init_single_client(self, name: str, cfg_dict: Dict[str, Any]) -> None:
        """Initialize a single MCP client and store in state."""
        state = self._state
        if not state:
            return

        try:
            result = await self._create_client(name, cfg_dict)
            state.status[name] = result["status"]
            if result.get("client"):
                state.clients[name] = result["client"]
        except Exception as e:
            log.error("failed to initialize MCP client", {"name": name, "error": str(e)})
            state.status[name] = MCPStatusFailed(error=str(e))

    async def _create_client(
        self,
        name: str,
        config: Dict[str, Any],
        use_oauth: bool = False,
    ) -> Dict[str, Any]:
        """Create an MCP client from configuration."""
        mcp_type = config.get("type")

        if mcp_type == "remote":
            return await self._create_remote_client(name, config, use_oauth=use_oauth)
        elif mcp_type == "local":
            return await self._create_local_client(name, config)
        else:
            return {
                "client": None,
                "status": MCPStatusFailed(error=f"Unknown MCP type: {mcp_type}")
            }

    async def _create_remote_client(
        self,
        name: str,
        config: Dict[str, Any],
        use_oauth: bool = False,
    ) -> Dict[str, Any]:
        """Create a remote MCP client using StreamableHTTP/SSE transport."""
        url = config.get("url")
        if not url:
            return {
                "client": None,
                "status": MCPStatusFailed(error="Missing URL for remote MCP")
            }

        timeout = config.get("timeout", DEFAULT_TIMEOUT)
        headers = config.get("headers")
        oauth_auth = None
        oauth_redirect_url: Optional[str] = None

        if use_oauth and config.get("oauth") is not False:
            from .oauth_provider import McpOAuthConfig, create_oauth_provider

            oauth_cfg = config.get("oauth") if isinstance(config.get("oauth"), dict) else {}
            mcp_oauth_config = McpOAuthConfig(
                client_id=oauth_cfg.get("clientId") if oauth_cfg else None,
                client_secret=oauth_cfg.get("clientSecret") if oauth_cfg else None,
                scope=oauth_cfg.get("scope") if oauth_cfg else None,
            )

            async def redirect_handler(auth_url: str) -> None:
                nonlocal oauth_redirect_url
                oauth_redirect_url = auth_url

            async def callback_handler() -> tuple[str, str | None]:
                raise RuntimeError("OAuth callback required")

            oauth_auth = create_oauth_provider(
                mcp_name=name,
                server_url=url,
                config=mcp_oauth_config,
                redirect_handler=redirect_handler,
                callback_handler=callback_handler,
            )

        client: MCPClient | None = None
        try:
            client = MCPClient(name=name)

            async with asyncio.timeout(timeout):
                await client.connect_remote(url, headers=headers, oauth_auth=oauth_auth)

            if client.connected:
                # Verify connection by listing tools
                try:
                    async with asyncio.timeout(timeout):
                        await client.list_tools()
                except asyncio.CancelledError as e:
                    if _is_external_cancellation():
                        raise
                    log.error("failed to list tools after connect", {
                        "name": name, "error": str(e)
                    })
                    await client.close()
                    return {
                        "client": None,
                        "status": MCPStatusFailed(error=str(e) or "MCP tool listing cancelled")
                    }
                except Exception as e:
                    log.error("failed to list tools after connect", {
                        "name": name, "error": str(e)
                    })
                    await client.close()
                    return {
                        "client": None,
                        "status": MCPStatusFailed(error=f"Failed to get tools: {e}")
                    }

                log.info("connected to remote MCP", {"name": name, "url": url})
                await Bus.publish(ToolsChanged, ToolsChangedProps(server=name))
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
        except asyncio.CancelledError as e:
            if _is_external_cancellation():
                raise
            if client and client.connected:
                await client.close()
            return {
                "client": None,
                "status": MCPStatusFailed(error=str(e) or "Connection cancelled")
            }
        except MCPAuthError as e:
            if _needs_registration(e.error_code):
                return {
                    "client": None,
                    "status": MCPStatusNeedsClientRegistration(
                        error="Server does not support dynamic client registration. Please provide clientId in config."
                    )
                }
            return {
                "client": None,
                "status": MCPStatusNeedsAuth()
            }
        except Exception as e:
            if oauth_redirect_url:
                return {
                    "client": None,
                    "status": MCPStatusNeedsAuth(),
                }
            error_msg = str(e)

            log.debug("remote MCP connection failed", {
                "name": name,
                "url": url,
                "error": error_msg,
            })
            return {
                "client": None,
                "status": MCPStatusFailed(error=error_msg)
            }

    async def _create_local_client(
        self,
        name: str,
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create a local MCP client using stdio transport."""
        command = config.get("command", [])
        if not command:
            return {
                "client": None,
                "status": MCPStatusFailed(error="Missing command for local MCP")
            }

        environment = config.get("environment") or {}
        timeout = config.get("timeout", DEFAULT_TIMEOUT)

        try:
            # Use process cwd — MCP servers are app-level, not instance-scoped
            cwd = os.getcwd()

            # Prepare environment
            env = os.environ.copy()
            env.update(environment)

            # Split command into executable + args
            cmd = command[0]
            args = command[1:] if len(command) > 1 else []

            client = MCPClient(name=name)

            async with asyncio.timeout(timeout):
                await client.connect_stdio(command=cmd, args=args, cwd=cwd, env=env)

            if client.connected:
                # Verify connection by listing tools
                try:
                    async with asyncio.timeout(timeout):
                        await client.list_tools()
                except Exception as e:
                    log.error("failed to list tools after connect", {
                        "name": name, "error": str(e)
                    })
                    await client.close()
                    return {
                        "client": None,
                        "status": MCPStatusFailed(error=f"Failed to get tools: {e}")
                    }

                log.info("connected to local MCP", {
                    "name": name,
                    "command": command,
                })
                await Bus.publish(ToolsChanged, ToolsChangedProps(server=name))
                return {
                    "client": client,
                    "status": MCPStatusConnected()
                }
            else:
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

    async def init(self) -> None:
        """Initialize MCP clients from configuration."""
        await self._get_state()

    async def status(self) -> Dict[str, MCPStatus]:
        """Get status of all configured MCP servers."""
        state = await self._get_state()
        config = await ConfigManager.get()
        mcp_config = config.mcp or {}

        result: Dict[str, MCPStatus] = {}
        for name, mcp in mcp_config.items():
            cfg_dict = _get_mcp_config_dict(mcp)
            if cfg_dict is None:
                continue
            result[name] = state.status.get(name, MCPStatusDisabled())

        return result

    async def clients(self) -> Dict[str, MCPClient]:
        """Get all connected MCP clients."""
        state = await self._get_state()
        return state.clients

    async def connect(self, name: str, use_oauth: bool = False) -> None:
        """Connect to a specific MCP server."""
        config = await ConfigManager.get()
        mcp_config = config.mcp or {}
        mcp = mcp_config.get(name)

        if not mcp:
            raise ValueError(f"MCP server not found: {name}")

        cfg_dict = _get_mcp_config_dict(mcp)
        if cfg_dict is None:
            raise ValueError(f"Invalid MCP config for server: {name}")

        # Force enabled
        cfg_dict = dict(cfg_dict)
        cfg_dict["enabled"] = True

        result = await self._create_client(name, cfg_dict, use_oauth=use_oauth)

        state = await self._get_state()
        state.status[name] = result["status"]

        if result.get("client"):
            # Close existing client if present
            if name in state.clients:
                await state.clients[name].close()
            state.clients[name] = result["client"]

    async def disconnect(self, name: str) -> None:
        """Disconnect from a specific MCP server."""
        config = await ConfigManager.get()
        mcp_config = config.mcp or {}
        if name not in mcp_config:
            raise ValueError(f"MCP server not found: {name}")

        state = await self._get_state()

        if name in state.clients:
            await state.clients[name].close()
            del state.clients[name]

        state.status[name] = MCPStatusDisabled()

    async def tools(self) -> Dict[str, Dict[str, Any]]:
        """Get all tools from connected MCP servers.

        Returns:
            Dictionary of tool_id to tool definition dict with keys:
            name, description, input_schema, client, timeout
        """
        state = await self._get_state()
        config = await ConfigManager.get()
        mcp_config = config.mcp or {}

        result: Dict[str, Dict[str, Any]] = {}

        for client_name, client in list(state.clients.items()):
            status = state.status.get(client_name)
            if not isinstance(status, MCPStatusConnected):
                continue

            try:
                tools = await client.list_tools()

                mcp_entry = mcp_config.get(client_name)
                cfg_dict = _get_mcp_config_dict(mcp_entry) if mcp_entry else None
                timeout = (cfg_dict.get("timeout", DEFAULT_TIMEOUT) if cfg_dict else DEFAULT_TIMEOUT)

                for tool in tools:
                    safe_client = _sanitize_name(client_name)
                    safe_tool = _sanitize_name(tool.name)
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

    async def prompts(self) -> Dict[str, Dict[str, Any]]:
        """Get all prompts from connected MCP servers."""
        state = await self._get_state()
        result: Dict[str, Dict[str, Any]] = {}

        for client_name, client in list(state.clients.items()):
            status = state.status.get(client_name)
            if not isinstance(status, MCPStatusConnected):
                continue

            try:
                prompts = await client.list_prompts()

                for prompt in prompts:
                    safe_client = _sanitize_name(client_name)
                    safe_prompt = _sanitize_name(prompt.get("name", ""))
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

    async def resources(self) -> Dict[str, MCPResource]:
        """Get all resources from connected MCP servers."""
        state = await self._get_state()
        result: Dict[str, MCPResource] = {}

        for client_name, client in list(state.clients.items()):
            status = state.status.get(client_name)
            if not isinstance(status, MCPStatusConnected):
                continue

            try:
                resources = await client.list_resources()

                for resource in resources:
                    safe_client = _sanitize_name(client_name)
                    safe_name = _sanitize_name(resource.get("name", ""))
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

    async def get_prompt(
        self,
        client_name: str,
        name: str,
        args: Optional[Dict[str, str]] = None
    ) -> Optional[Any]:
        """Get a specific prompt from an MCP server."""
        state = await self._get_state()
        client = state.clients.get(client_name)

        if not client:
            log.warn("client not found for prompt", {"client": client_name})
            return None

        try:
            return await client.get_prompt(name, args)
        except Exception as e:
            log.error("failed to get prompt from MCP server", {
                "client": client_name,
                "prompt": name,
                "error": str(e),
            })
            return None

    async def read_resource(
        self,
        client_name: str,
        resource_uri: str
    ) -> Optional[Any]:
        """Read a resource from an MCP server."""
        state = await self._get_state()
        client = state.clients.get(client_name)

        if not client:
            log.warn("client not found for resource", {"client": client_name})
            return None

        try:
            return await client.read_resource(resource_uri)
        except Exception as e:
            log.error("failed to read resource from MCP server", {
                "client": client_name,
                "uri": resource_uri,
                "error": str(e),
            })
            return None

    async def supports_oauth(self, mcp_name: str) -> bool:
        """Check if an MCP server supports OAuth.

        Remote servers support OAuth by default unless explicitly disabled.
        """
        config = await ConfigManager.get()
        mcp_config = config.mcp or {}
        mcp = mcp_config.get(mcp_name)

        if not mcp:
            return False

        cfg_dict = _get_mcp_config_dict(mcp)
        if cfg_dict is None:
            return False

        return cfg_dict.get("type") == "remote" and cfg_dict.get("oauth") is not False

    async def has_stored_tokens(self, mcp_name: str) -> bool:
        """Check if an MCP server has stored OAuth tokens."""
        entry = await McpAuth.get(mcp_name)
        return entry is not None and entry.tokens is not None

    async def get_auth_status(
        self,
        mcp_name: str
    ) -> Literal["authenticated", "expired", "not_authenticated"]:
        """Get the authentication status for an MCP server."""
        has_tokens = await self.has_stored_tokens(mcp_name)
        if not has_tokens:
            return "not_authenticated"

        expired = await McpAuth.is_token_expired(mcp_name)
        return "expired" if expired else "authenticated"

    async def start_auth(self, mcp_name: str) -> Dict[str, str]:
        """Start OAuth authentication flow for an MCP server.

        Returns dict with 'authorization_url' key (empty if already authenticated).
        """
        from .oauth_callback import McpOAuthCallback
        from .oauth_provider import McpOAuthConfig, create_oauth_provider

        async with self._auth_lock(mcp_name):
            pending = self._pending_auth.get(mcp_name)
            if pending is None:
                config = await ConfigManager.get()
                mcp_config = config.mcp or {}
                mcp = mcp_config.get(mcp_name)

                if not mcp:
                    raise ValueError(f"MCP server not found: {mcp_name}")

                cfg_dict = _get_mcp_config_dict(mcp)
                if cfg_dict is None:
                    raise ValueError(f"MCP server {mcp_name} is disabled or missing configuration")

                if cfg_dict.get("type") != "remote":
                    raise ValueError(f"MCP server {mcp_name} is not a remote server")

                if cfg_dict.get("oauth") is False:
                    raise ValueError(f"MCP server {mcp_name} has OAuth explicitly disabled")

                # Start the callback server
                await McpOAuthCallback.ensure_running()

                # Build OAuth config from config entry
                oauth_cfg = cfg_dict.get("oauth") if isinstance(cfg_dict.get("oauth"), dict) else {}
                mcp_oauth_config = McpOAuthConfig(
                    client_id=oauth_cfg.get("clientId") if oauth_cfg else None,
                    client_secret=oauth_cfg.get("clientSecret") if oauth_cfg else None,
                    scope=oauth_cfg.get("scope") if oauth_cfg else None,
                )

                loop = asyncio.get_running_loop()
                callback_future: asyncio.Future[tuple[str, str | None]] = loop.create_future()
                url_future: asyncio.Future[str] = loop.create_future()

                async def redirect_handler(auth_url: str) -> None:
                    parsed = parse_qs(urlparse(auth_url).query)
                    state_values = parsed.get("state")
                    oauth_state = state_values[0] if state_values else ""
                    if oauth_state:
                        await McpAuth.update_oauth_state(mcp_name, oauth_state)
                    if not url_future.done():
                        url_future.set_result(auth_url)

                async def callback_handler() -> tuple[str, str | None]:
                    return await callback_future

                auth_provider = create_oauth_provider(
                    mcp_name=mcp_name,
                    server_url=cfg_dict["url"],
                    config=mcp_oauth_config,
                    redirect_handler=redirect_handler,
                    callback_handler=callback_handler,
                )

                async def auth_probe() -> Dict[str, str]:
                    import httpx
                    from mcp import ClientSession
                    from mcp.client.streamable_http import streamable_http_client

                    async with httpx.AsyncClient(auth=auth_provider, follow_redirects=True) as http_client:
                        async with streamable_http_client(cfg_dict["url"], http_client=http_client) as (read, write, _):
                            async with ClientSession(read, write) as session:
                                await session.initialize()
                                return {"authorization_url": ""}

                pending = PendingAuthFlow(
                    auth_task=asyncio.create_task(auth_probe()),
                    callback_future=callback_future,
                    url_future=url_future,
                )
                self._pending_auth[mcp_name] = pending

            done, _ = await asyncio.wait(
                {pending.auth_task, pending.url_future},
                return_when=asyncio.FIRST_COMPLETED,
                timeout=10.0,
            )

            if not done:
                await self._clear_pending_auth(mcp_name, cancel_task=True)
                raise RuntimeError("OAuth flow did not produce an authorization URL")

            if pending.auth_task in done:
                try:
                    return pending.auth_task.result()
                finally:
                    await self._clear_pending_auth(mcp_name)

            return {"authorization_url": pending.url_future.result()}

    async def finish_auth(
        self,
        mcp_name: str,
        code: str,
        state: str,
    ) -> MCPStatus:
        """Complete OAuth authentication with code+state and reconnect."""
        flow = self._pending_auth.get(mcp_name)
        if flow is None:
            raise RuntimeError(f"No pending OAuth flow for MCP server: {mcp_name}")

        stored_state = await McpAuth.get_oauth_state(mcp_name)
        if stored_state != state:
            await McpAuth.clear_oauth_state(mcp_name)
            await self._clear_pending_auth(mcp_name, cancel_task=True)
            raise RuntimeError("OAuth state mismatch - potential CSRF attack")

        if not flow.callback_future.done():
            flow.callback_future.set_result((code, state))

        try:
            auth_result = await flow.auth_task
        except Exception:
            await self._clear_pending_auth(mcp_name, cancel_task=True)
            raise
        if auth_result.get("authorization_url"):
            await self._clear_pending_auth(mcp_name, cancel_task=True)
            raise RuntimeError("OAuth flow did not complete token exchange")

        await McpAuth.clear_oauth_state(mcp_name)
        await McpAuth.clear_code_verifier(mcp_name)
        await self._clear_pending_auth(mcp_name)

        await self.connect(mcp_name, use_oauth=True)
        state_map = await self._get_state()
        return state_map.status.get(mcp_name, MCPStatusFailed(error="Unknown error after auth"))

    async def authenticate(self, mcp_name: str) -> MCPStatus:
        """Complete OAuth authentication — opens browser and waits for callback."""
        import webbrowser
        from .oauth_callback import McpOAuthCallback

        result = await self.start_auth(mcp_name)
        auth_url = result.get("authorization_url", "")

        if not auth_url:
            # Already authenticated, reconnect
            await self.connect(mcp_name, use_oauth=True)
            state = await self._get_state()
            return state.status.get(mcp_name, MCPStatusConnected())

        oauth_state = await McpAuth.get_oauth_state(mcp_name)
        if not oauth_state:
            parsed = parse_qs(urlparse(auth_url).query)
            state_values = parsed.get("state")
            oauth_state = state_values[0] if state_values else ""
            if not oauth_state:
                raise RuntimeError("OAuth state not found")
            await McpAuth.update_oauth_state(mcp_name, oauth_state)

        log.info("opening browser for oauth", {"mcp_name": mcp_name, "url": auth_url})

        callback_promise = McpOAuthCallback.wait_for_callback(oauth_state, mcp_name=mcp_name)

        try:
            webbrowser.open(auth_url)
        except Exception:
            log.warn("failed to open browser, user must open URL manually", {"mcp_name": mcp_name})
            await Bus.publish(BrowserOpenFailed, BrowserOpenFailedProps(mcp_name=mcp_name, url=auth_url))

        code = await callback_promise
        return await self.finish_auth(mcp_name, code=code, state=oauth_state)

    async def remove_auth(self, mcp_name: str) -> None:
        """Remove OAuth credentials for an MCP server."""
        from .oauth_callback import McpOAuthCallback

        await McpAuth.remove(mcp_name)
        McpOAuthCallback.cancel_pending(mcp_name)
        await McpAuth.clear_oauth_state(mcp_name)
        await McpAuth.clear_code_verifier(mcp_name)
        await self._clear_pending_auth(mcp_name, cancel_task=True)
        log.info("removed oauth credentials", {"mcp_name": mcp_name})

    async def shutdown(self) -> None:
        """Shutdown all MCP clients."""
        if self._state:
            for client in self._state.clients.values():
                try:
                    await client.close()
                except Exception as e:
                    log.error("Failed to close MCP client", {"error": str(e)})
            self._state = None
