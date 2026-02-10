"""MCP OAuth callback server.

This module provides a local HTTP server to receive OAuth callbacks
during the authentication flow for remote MCP servers.

The server listens on a fixed port and handles the OAuth redirect,
extracting the authorization code and passing it back to the auth flow.
"""

import asyncio
from typing import Callable, Dict, Optional
import socket

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, Response
from starlette.routing import Route

from ..util.log import Log

log = Log.create({"service": "mcp.oauth-callback"})

# OAuth callback configuration
OAUTH_CALLBACK_PORT = 19876
OAUTH_CALLBACK_PATH = "/mcp/oauth/callback"

# Callback timeout (5 minutes)
CALLBACK_TIMEOUT_MS = 5 * 60 * 1000

# HTML templates for success/error pages
HTML_SUCCESS = """<!DOCTYPE html>
<html>
<head>
  <title>Hotaru Code - Authorization Successful</title>
  <style>
    body { font-family: system-ui, -apple-system, sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; background: #1a1a2e; color: #eee; }
    .container { text-align: center; padding: 2rem; }
    h1 { color: #4ade80; margin-bottom: 1rem; }
    p { color: #aaa; }
  </style>
</head>
<body>
  <div class="container">
    <h1>Authorization Successful</h1>
    <p>You can close this window and return to Hotaru Code.</p>
  </div>
  <script>setTimeout(() => window.close(), 2000);</script>
</body>
</html>"""


def html_error(error: str) -> str:
    """Generate error HTML page.

    Args:
        error: Error message to display

    Returns:
        HTML string for error page
    """
    return f"""<!DOCTYPE html>
<html>
<head>
  <title>Hotaru Code - Authorization Failed</title>
  <style>
    body {{ font-family: system-ui, -apple-system, sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; background: #1a1a2e; color: #eee; }}
    .container {{ text-align: center; padding: 2rem; }}
    h1 {{ color: #f87171; margin-bottom: 1rem; }}
    p {{ color: #aaa; }}
    .error {{ color: #fca5a5; font-family: monospace; margin-top: 1rem; padding: 1rem; background: rgba(248,113,113,0.1); border-radius: 0.5rem; }}
  </style>
</head>
<body>
  <div class="container">
    <h1>Authorization Failed</h1>
    <p>An error occurred during authorization.</p>
    <div class="error">{error}</div>
  </div>
</body>
</html>"""


class PendingAuth:
    """Represents a pending OAuth authorization.

    Attributes:
        future: Future that will be resolved with the auth code
        timeout_task: Task that will cancel the auth after timeout
    """

    def __init__(self):
        self.future: asyncio.Future[str] = asyncio.get_event_loop().create_future()
        self.timeout_task: Optional[asyncio.Task] = None


class McpOAuthCallback:
    """OAuth callback server for MCP authentication.

    Provides a local HTTP server to receive OAuth redirects and
    extract authorization codes for the authentication flow.
    """

    _server: Optional[asyncio.Server] = None
    _app: Optional[Starlette] = None
    _pending_auths: Dict[str, PendingAuth] = {}  # keyed by OAuth state
    _mcp_to_state: Dict[str, str] = {}  # mcp_name -> OAuth state (reverse mapping)

    @classmethod
    async def _handle_callback(cls, request: Request) -> Response:
        """Handle OAuth callback request.

        Args:
            request: Incoming HTTP request

        Returns:
            HTML response indicating success or failure
        """
        code = request.query_params.get("code")
        state = request.query_params.get("state")
        error = request.query_params.get("error")
        error_description = request.query_params.get("error_description")

        log.info("received oauth callback", {
            "has_code": bool(code),
            "state": state,
            "error": error
        })

        # Enforce state parameter presence
        if not state:
            error_msg = "Missing required state parameter - potential CSRF attack"
            log.error("oauth callback missing state parameter", {
                "url": str(request.url)
            })
            return HTMLResponse(html_error(error_msg), status_code=400)

        if error:
            error_msg = error_description or error
            if state in cls._pending_auths:
                pending = cls._pending_auths.pop(state)
                if pending.timeout_task:
                    pending.timeout_task.cancel()
                pending.future.set_exception(Exception(error_msg))
                cls._mcp_to_state = {k: v for k, v in cls._mcp_to_state.items() if v != state}
            return HTMLResponse(html_error(error_msg))

        if not code:
            return HTMLResponse(
                html_error("No authorization code provided"),
                status_code=400
            )

        # Validate state parameter
        if state not in cls._pending_auths:
            error_msg = "Invalid or expired state parameter - potential CSRF attack"
            log.error("oauth callback with invalid state", {
                "state": state,
                "pending_states": list(cls._pending_auths.keys())
            })
            return HTMLResponse(html_error(error_msg), status_code=400)

        pending = cls._pending_auths.pop(state)
        if pending.timeout_task:
            pending.timeout_task.cancel()
        pending.future.set_result(code)

        # Clean up reverse mapping
        cls._mcp_to_state = {k: v for k, v in cls._mcp_to_state.items() if v != state}

        return HTMLResponse(HTML_SUCCESS)

    @classmethod
    async def _handle_not_found(cls, request: Request) -> Response:
        """Handle requests to unknown paths."""
        return Response("Not found", status_code=404)

    @classmethod
    def _create_app(cls) -> Starlette:
        """Create the Starlette application."""
        routes = [
            Route(OAUTH_CALLBACK_PATH, cls._handle_callback, methods=["GET"]),
        ]
        return Starlette(routes=routes)

    @classmethod
    async def is_port_in_use(cls) -> bool:
        """Check if the callback port is already in use.

        Returns:
            True if port is in use, False otherwise
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(("127.0.0.1", OAUTH_CALLBACK_PORT))
            sock.close()
            return result == 0
        except Exception:
            return False

    @classmethod
    async def ensure_running(cls) -> None:
        """Ensure the OAuth callback server is running.

        Starts the server if not already running. If another instance
        is already using the port, logs a message and returns.
        """
        if cls._server:
            return

        if await cls.is_port_in_use():
            log.info("oauth callback server already running on another instance", {
                "port": OAUTH_CALLBACK_PORT
            })
            return

        import uvicorn

        cls._app = cls._create_app()

        config = uvicorn.Config(
            cls._app,
            host="127.0.0.1",
            port=OAUTH_CALLBACK_PORT,
            log_level="warning",
        )

        server = uvicorn.Server(config)

        # Start server in background
        asyncio.create_task(server.serve())

        # Wait for server to be ready
        while not server.started:
            await asyncio.sleep(0.1)

        cls._server = server  # type: ignore

        log.info("oauth callback server started", {"port": OAUTH_CALLBACK_PORT})

    @classmethod
    async def wait_for_callback(cls, oauth_state: str, mcp_name: Optional[str] = None) -> str:
        """Wait for OAuth callback with the given state.

        Args:
            oauth_state: The state parameter to wait for
            mcp_name: Optional MCP server name for reverse lookup in cancel_pending

        Returns:
            The authorization code from the callback

        Raises:
            Exception: If callback times out or fails
        """
        pending = PendingAuth()

        async def timeout():
            await asyncio.sleep(CALLBACK_TIMEOUT_MS / 1000)
            if oauth_state in cls._pending_auths:
                del cls._pending_auths[oauth_state]
                if mcp_name and mcp_name in cls._mcp_to_state:
                    del cls._mcp_to_state[mcp_name]
                pending.future.set_exception(
                    Exception("OAuth callback timeout - authorization took too long")
                )

        pending.timeout_task = asyncio.create_task(timeout())
        cls._pending_auths[oauth_state] = pending

        # Register reverse mapping so cancel_pending(mcp_name) works
        if mcp_name:
            cls._mcp_to_state[mcp_name] = oauth_state

        return await pending.future

    @classmethod
    def cancel_pending(cls, mcp_name: str) -> None:
        """Cancel a pending OAuth authorization.

        Args:
            mcp_name: Name of the MCP server
        """
        # Look up the OAuth state for this MCP server
        oauth_state = cls._mcp_to_state.pop(mcp_name, None)
        if oauth_state and oauth_state in cls._pending_auths:
            pending = cls._pending_auths.pop(oauth_state)
            if pending.timeout_task:
                pending.timeout_task.cancel()
            if not pending.future.done():
                pending.future.set_exception(Exception("Authorization cancelled"))

    @classmethod
    async def stop(cls) -> None:
        """Stop the OAuth callback server."""
        if cls._server:
            cls._server.should_exit = True  # type: ignore
            await asyncio.sleep(0.5)
            cls._server = None
            cls._app = None
            log.info("oauth callback server stopped")

        # Cancel all pending auths
        for state, pending in list(cls._pending_auths.items()):
            if pending.timeout_task:
                pending.timeout_task.cancel()
            if not pending.future.done():
                pending.future.set_exception(
                    Exception("OAuth callback server stopped")
                )
        cls._pending_auths.clear()
        cls._mcp_to_state.clear()

    @classmethod
    def is_running(cls) -> bool:
        """Check if the callback server is running.

        Returns:
            True if server is running, False otherwise
        """
        return cls._server is not None
