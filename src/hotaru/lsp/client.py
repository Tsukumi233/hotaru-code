"""LSP client implementation.

This module provides the LSP client that communicates with language servers
using the JSON-RPC protocol over stdio.
"""

import asyncio
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set
from urllib.parse import quote
from pydantic import BaseModel

from ..core.bus import Bus, BusEvent
from ..project.instance import Instance
from ..util.log import Log
from .language import LANGUAGE_EXTENSIONS
from .server import LSPServerHandle

log = Log.create({"service": "lsp.client"})

# Debounce time for diagnostics
DIAGNOSTICS_DEBOUNCE_MS = 150


class DiagnosticsEventProps(BaseModel):
    """Properties for diagnostics event."""
    server_id: str
    path: str


# Event for diagnostics updates
DiagnosticsEvent = BusEvent.define("lsp.client.diagnostics", DiagnosticsEventProps)


class LSPDiagnostic(BaseModel):
    """LSP diagnostic information.

    Attributes:
        range: Location of the diagnostic
        message: Diagnostic message
        severity: Severity level (1=Error, 2=Warning, 3=Info, 4=Hint)
        source: Source of the diagnostic (e.g., "pyright")
        code: Optional diagnostic code
    """
    range: Dict[str, Any]
    message: str
    severity: int = 1
    source: Optional[str] = None
    code: Optional[Any] = None


class LSPClient:
    """LSP client for communicating with a language server.

    Handles the JSON-RPC protocol over stdio and provides methods
    for common LSP operations.
    """

    def __init__(
        self,
        server_id: str,
        server: LSPServerHandle,
        root: str
    ):
        """Initialize LSP client.

        Args:
            server_id: Identifier for the server
            server: Handle to the server process
            root: Project root directory
        """
        self.server_id = server_id
        self.server = server
        self.root = root
        self._diagnostics: Dict[str, List[LSPDiagnostic]] = {}
        self._files: Dict[str, int] = {}  # path -> version
        self._request_id = 0
        self._pending_requests: Dict[int, asyncio.Future] = {}
        self._reader_task: Optional[asyncio.Task] = None
        self._initialized = False

    async def initialize(self) -> bool:
        """Initialize the LSP connection.

        Returns:
            True if initialization successful
        """
        if self._initialized:
            return True

        # Start reader task
        self._reader_task = asyncio.create_task(self._read_messages())

        # Send initialize request
        root_uri = self._path_to_uri(self.root)

        try:
            result = await asyncio.wait_for(
                self._send_request("initialize", {
                    "rootUri": root_uri,
                    "processId": self.server.process.pid,
                    "workspaceFolders": [
                        {"name": "workspace", "uri": root_uri}
                    ],
                    "initializationOptions": self.server.initialization,
                    "capabilities": {
                        "window": {"workDoneProgress": True},
                        "workspace": {
                            "configuration": True,
                            "didChangeWatchedFiles": {"dynamicRegistration": True},
                        },
                        "textDocument": {
                            "synchronization": {"didOpen": True, "didChange": True},
                            "publishDiagnostics": {"versionSupport": True},
                        },
                    },
                }),
                timeout=45.0
            )

            # Send initialized notification
            await self._send_notification("initialized", {})

            # Send configuration if available
            if self.server.initialization:
                await self._send_notification("workspace/didChangeConfiguration", {
                    "settings": self.server.initialization
                })

            self._initialized = True
            log.info("LSP client initialized", {"server_id": self.server_id})
            return True

        except asyncio.TimeoutError:
            log.error("LSP initialize timeout", {"server_id": self.server_id})
            return False
        except Exception as e:
            log.error("LSP initialize error", {
                "server_id": self.server_id,
                "error": str(e)
            })
            return False

    async def _read_messages(self) -> None:
        """Read messages from the server."""
        stdout = self.server.process.stdout
        if not stdout:
            return

        buffer = b""

        while True:
            try:
                # Read data
                chunk = await asyncio.get_event_loop().run_in_executor(
                    None, stdout.read, 4096
                )
                if not chunk:
                    break

                buffer += chunk

                # Parse messages from buffer
                while True:
                    # Find header end
                    header_end = buffer.find(b"\r\n\r\n")
                    if header_end == -1:
                        break

                    # Parse headers
                    header_data = buffer[:header_end].decode("utf-8")
                    content_length = 0

                    for line in header_data.split("\r\n"):
                        if line.lower().startswith("content-length:"):
                            content_length = int(line.split(":")[1].strip())

                    if content_length == 0:
                        buffer = buffer[header_end + 4:]
                        continue

                    # Check if we have full message
                    message_start = header_end + 4
                    message_end = message_start + content_length

                    if len(buffer) < message_end:
                        break

                    # Parse message
                    message_data = buffer[message_start:message_end].decode("utf-8")
                    buffer = buffer[message_end:]

                    try:
                        message = json.loads(message_data)
                        await self._handle_message(message)
                    except json.JSONDecodeError:
                        log.error("Invalid JSON from LSP server")

            except Exception as e:
                log.error("Error reading LSP messages", {"error": str(e)})
                break

    async def _handle_message(self, message: Dict[str, Any]) -> None:
        """Handle an incoming message from the server.

        Args:
            message: Parsed JSON-RPC message
        """
        if "id" in message and "result" in message:
            # Response to a request
            request_id = message["id"]
            if request_id in self._pending_requests:
                self._pending_requests[request_id].set_result(message.get("result"))

        elif "id" in message and "error" in message:
            # Error response
            request_id = message["id"]
            if request_id in self._pending_requests:
                error = message["error"]
                self._pending_requests[request_id].set_exception(
                    Exception(error.get("message", "Unknown error"))
                )

        elif "method" in message:
            # Notification or request from server
            method = message["method"]
            params = message.get("params", {})

            if method == "textDocument/publishDiagnostics":
                await self._handle_diagnostics(params)
            elif method == "window/workDoneProgress/create":
                # Acknowledge progress creation
                if "id" in message:
                    await self._send_response(message["id"], None)
            elif method == "workspace/configuration":
                # Return configuration
                if "id" in message:
                    await self._send_response(
                        message["id"],
                        [self.server.initialization or {}]
                    )
            elif method == "client/registerCapability":
                if "id" in message:
                    await self._send_response(message["id"], None)
            elif method == "client/unregisterCapability":
                if "id" in message:
                    await self._send_response(message["id"], None)
            elif method == "workspace/workspaceFolders":
                if "id" in message:
                    await self._send_response(message["id"], [
                        {"name": "workspace", "uri": self._path_to_uri(self.root)}
                    ])

    async def _handle_diagnostics(self, params: Dict[str, Any]) -> None:
        """Handle diagnostics notification.

        Args:
            params: Diagnostics parameters
        """
        uri = params.get("uri", "")
        file_path = self._uri_to_path(uri)

        diagnostics = [
            LSPDiagnostic.model_validate(d)
            for d in params.get("diagnostics", [])
        ]

        log.info("textDocument/publishDiagnostics", {
            "path": file_path,
            "count": len(diagnostics)
        })

        self._diagnostics[file_path] = diagnostics

        # Publish event
        await Bus.publish(DiagnosticsEvent, DiagnosticsEventProps(
            server_id=self.server_id,
            path=file_path
        ))

    async def _send_request(
        self,
        method: str,
        params: Dict[str, Any]
    ) -> Any:
        """Send a request to the server.

        Args:
            method: JSON-RPC method name
            params: Method parameters

        Returns:
            Response result
        """
        self._request_id += 1
        request_id = self._request_id

        message = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_requests[request_id] = future

        await self._send_message(message)

        try:
            return await future
        finally:
            self._pending_requests.pop(request_id, None)

    async def _send_notification(
        self,
        method: str,
        params: Dict[str, Any]
    ) -> None:
        """Send a notification to the server.

        Args:
            method: JSON-RPC method name
            params: Method parameters
        """
        message = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        await self._send_message(message)

    async def _send_response(
        self,
        request_id: int,
        result: Any
    ) -> None:
        """Send a response to a server request.

        Args:
            request_id: Request ID to respond to
            result: Response result
        """
        message = {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result,
        }
        await self._send_message(message)

    async def _send_message(self, message: Dict[str, Any]) -> None:
        """Send a message to the server.

        Args:
            message: Message to send
        """
        stdin = self.server.process.stdin
        if not stdin:
            return

        content = json.dumps(message)
        content_bytes = content.encode("utf-8")

        header = f"Content-Length: {len(content_bytes)}\r\n\r\n"
        data = header.encode("utf-8") + content_bytes

        await asyncio.get_event_loop().run_in_executor(
            None, stdin.write, data
        )
        await asyncio.get_event_loop().run_in_executor(
            None, stdin.flush
        )

    def _path_to_uri(self, path: str) -> str:
        """Convert a file path to a file URI.

        Args:
            path: File path

        Returns:
            File URI
        """
        path = os.path.abspath(path)
        if os.name == "nt":
            # Windows: file:///C:/path
            path = "/" + path.replace("\\", "/")
        return "file://" + quote(path, safe="/:")

    def _uri_to_path(self, uri: str) -> str:
        """Convert a file URI to a file path.

        Args:
            uri: File URI

        Returns:
            File path
        """
        from urllib.parse import unquote, urlparse

        parsed = urlparse(uri)
        path = unquote(parsed.path)

        if os.name == "nt" and path.startswith("/"):
            # Windows: remove leading slash
            path = path[1:]

        return os.path.normpath(path)

    async def open_file(self, path: str) -> None:
        """Notify the server that a file was opened.

        Args:
            path: File path
        """
        if not os.path.isabs(path):
            path = os.path.join(Instance.directory(), path)

        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception as e:
            log.error("Failed to read file", {"path": path, "error": str(e)})
            return

        extension = os.path.splitext(path)[1]
        language_id = LANGUAGE_EXTENSIONS.get(extension, "plaintext")
        uri = self._path_to_uri(path)

        version = self._files.get(path)

        if version is not None:
            # File already open, send change notification
            await self._send_notification("workspace/didChangeWatchedFiles", {
                "changes": [{"uri": uri, "type": 2}]  # Changed
            })

            new_version = version + 1
            self._files[path] = new_version

            await self._send_notification("textDocument/didChange", {
                "textDocument": {"uri": uri, "version": new_version},
                "contentChanges": [{"text": text}],
            })
        else:
            # New file, send open notification
            await self._send_notification("workspace/didChangeWatchedFiles", {
                "changes": [{"uri": uri, "type": 1}]  # Created
            })

            self._diagnostics.pop(path, None)

            await self._send_notification("textDocument/didOpen", {
                "textDocument": {
                    "uri": uri,
                    "languageId": language_id,
                    "version": 0,
                    "text": text,
                },
            })

            self._files[path] = 0

    async def wait_for_diagnostics(self, path: str, timeout: float = 3.0) -> None:
        """Wait for diagnostics for a file.

        Args:
            path: File path
            timeout: Maximum time to wait in seconds
        """
        if not os.path.isabs(path):
            path = os.path.join(Instance.directory(), path)

        path = os.path.normpath(path)
        log.info("waiting for diagnostics", {"path": path})

        event = asyncio.Event()
        debounce_task: Optional[asyncio.Task] = None

        def on_diagnostics(payload):
            nonlocal debounce_task
            if (payload.properties.get("path") == path and
                payload.properties.get("server_id") == self.server_id):
                # Debounce to allow follow-up diagnostics
                if debounce_task:
                    debounce_task.cancel()

                async def set_event():
                    await asyncio.sleep(DIAGNOSTICS_DEBOUNCE_MS / 1000)
                    event.set()

                debounce_task = asyncio.create_task(set_event())

        unsubscribe = Bus.subscribe(DiagnosticsEvent, on_diagnostics)

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            log.info("got diagnostics", {"path": path})
        except asyncio.TimeoutError:
            pass
        finally:
            if debounce_task:
                debounce_task.cancel()
            unsubscribe()

    @property
    def diagnostics(self) -> Dict[str, List[LSPDiagnostic]]:
        """Get all diagnostics.

        Returns:
            Dictionary of file path to diagnostics
        """
        return self._diagnostics

    async def shutdown(self) -> None:
        """Shutdown the LSP client."""
        log.info("shutting down", {"server_id": self.server_id})

        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass

        # Kill the server process
        self.server.process.terminate()
        try:
            self.server.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.server.process.kill()

        log.info("shutdown complete", {"server_id": self.server_id})
