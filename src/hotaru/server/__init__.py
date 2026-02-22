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
    GET /healthz/web - WebUI readiness check
    GET / - WebUI index
    GET /web/{path} - WebUI static assets
    GET /v1/path - Get path information
    GET /v1/skill - List skills
    GET /v1/providers - List providers
    GET /v1/providers/{provider_id}/models - List models for a provider
    GET /v1/agents - List agents
    GET /v1/sessions - List sessions
    GET /v1/sessions/{session_id} - Get session details
    GET /v1/events - SSE event stream
"""

from .server import Server, ServerInfo

__all__ = [
    "Server",
    "ServerInfo",
]
