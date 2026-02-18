"""HTTP API server for Hotaru Code.

This module provides an HTTP server that exposes Hotaru Code functionality
to external clients such as IDEs, web interfaces, and other tools.

Example:
    from hotaru.server import Server

    # Start the server
    info = await Server.start(port=4096)
    print(f"Server running at {info.url}")

    # Stop the server
    await Server.stop()

API Endpoints:
    GET /health - Health check
    GET /v1/path - Get path information
    GET /v1/skill - List skills
    GET /v1/provider - List providers
    GET /v1/provider/{id}/model - List models for a provider
    GET /v1/agent - List agents
    GET /v1/session - List sessions
    GET /v1/session/{id} - Get session details
    GET /v1/event - SSE event stream
"""

from .server import Server, ServerInfo

__all__ = [
    "Server",
    "ServerInfo",
]
