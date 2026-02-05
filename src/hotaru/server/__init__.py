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
    GET /path - Get path information
    GET /provider - List providers
    GET /provider/{id}/model - List models for a provider
    GET /agent - List agents
    GET /skill - List skills
    GET /session - List sessions
    GET /session/{id} - Get session details
    GET /event - SSE event stream
"""

from .server import Server, ServerInfo

__all__ = [
    "Server",
    "ServerInfo",
]
