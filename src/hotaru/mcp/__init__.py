"""Model Context Protocol (MCP) client implementation.

This module provides MCP client functionality for connecting to MCP servers
and exposing their tools to the AI agent.

MCP servers can be:
- Remote: HTTP/SSE-based servers with optional OAuth authentication
- Local: Stdio-based servers running as subprocesses

Example:
    from hotaru.mcp import MCP

    # Initialize MCP clients from config
    await MCP.init()

    # Get available tools
    tools = await MCP.tools()

    # Get server status
    status = await MCP.status()
"""

from .mcp import MCP, MCPStatus, MCPResource
from .oauth_provider import McpOAuthConfig, McpTokenStorage, create_oauth_provider

__all__ = [
    "MCP",
    "MCPStatus",
    "MCPResource",
    "McpOAuthConfig",
    "McpTokenStorage",
    "create_oauth_provider",
]
