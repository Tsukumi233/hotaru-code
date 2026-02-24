"""LSP client implementation.

This module provides the LSP client that communicates with language servers
using the JSON-RPC protocol over stdio.
"""

import asyncio
import os
import subprocess
from contextvars import Context, copy_context
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import quote
from pydantic import BaseModel
from pylsp_jsonrpc.streams import JsonRpcStreamReader, JsonRpcStreamWriter

from ..project.instance import Instance
from ..util.log import Log
from .language import LANGUAGE_EXTENSIONS
from .server import LSPServerHandle

log = Log.create({"service": "lsp.client"})

# Debounce time for diagnostics
DIAGNOSTICS_DEBOUNCE_MS = 150


@dataclass(slots=True)
class _DiagWaiter:
    event: asyncio.Event
    task: asyncio.Task[None] | None = None


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
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stream_reader: Optional[JsonRpcStreamReader] = None
        self._stream_writer: Optional[JsonRpcStreamWriter] = None
        self._initialized = False
        self._diag_waiters: Dict[str, List[_DiagWaiter]] = {}
        self._loop_context: Context | None = None

    async def initialize(self) -> bool:
        """Initialize the LSP connection.

        Returns:
            True if initialization successful
        """
        if self._initialized:
            return True

        self._loop = asyncio.get_running_loop()
        self._loop_context = copy_context()

        stdout = self.server.process.stdout
        stdin = self.server.process.stdin
        if not stdout or not stdin:
            log.error("LSP server stdio not available", {"server_id": self.server_id})
            return False

        self._stream_reader = JsonRpcStreamReader(stdout)
        self._stream_writer = JsonRpcStreamWriter(stdin)

        # Start reader task
        self._reader_task = asyncio.create_task(self._read_messages())

        # Send initialize request
        root_uri = self._path_to_uri(self.root)

        try:
            await asyncio.wait_for(
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
        if not self._stream_reader:
            return

        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                None,
                self._stream_reader.listen,
                self._consume_message_from_reader_thread,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error("Error reading LSP messages", {"error": str(e)})

    def _consume_message_from_reader_thread(self, message: Dict[str, Any]) -> None:
        """Bridge reader-thread messages into the asyncio event loop."""
        if not self._loop or self._loop.is_closed():
            return

        if self._loop_context:
            self._loop.call_soon_threadsafe(
                self._schedule_message,
                message,
                context=self._loop_context,
            )
            return

        self._loop.call_soon_threadsafe(self._schedule_message, message)

    def _schedule_message(self, message: Dict[str, Any]) -> None:
        task = asyncio.create_task(self._handle_message(message))
        task.add_done_callback(self._on_message_done)

    def _on_message_done(self, task: asyncio.Task[None]) -> None:
        try:
            task.result()
        except Exception as e:
            log.error("Error handling LSP message", {
                "server_id": self.server_id,
                "error": str(e),
            })

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
        self._notify_waiters(file_path)

    def _notify_waiters(self, path: str) -> None:
        waiters = self._diag_waiters.get(path)
        if not waiters:
            return

        for waiter in waiters:
            if waiter.task:
                waiter.task.cancel()
            waiter.task = asyncio.create_task(self._debounce_waiter(waiter))

    async def _debounce_waiter(self, waiter: _DiagWaiter) -> None:
        await asyncio.sleep(DIAGNOSTICS_DEBOUNCE_MS / 1000)
        waiter.event.set()

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
        request_id: Any,
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
        if not self._stream_writer:
            return

        await asyncio.get_event_loop().run_in_executor(
            None, self._stream_writer.write, message
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

        waiter = _DiagWaiter(event=asyncio.Event())
        self._diag_waiters.setdefault(path, []).append(waiter)

        try:
            await asyncio.wait_for(waiter.event.wait(), timeout=timeout)
            log.info("got diagnostics", {"path": path})
        except asyncio.TimeoutError:
            pass
        finally:
            if waiter.task:
                waiter.task.cancel()

            waiters = self._diag_waiters.get(path)
            if not waiters:
                return

            if waiter in waiters:
                waiters.remove(waiter)
            if waiters:
                return

            self._diag_waiters.pop(path, None)

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

        if self._stream_writer:
            try:
                self._stream_writer.close()
            except Exception:
                pass

        # Terminate the server process first to unblock reader threads.
        self.server.process.terminate()
        try:
            await asyncio.to_thread(self.server.process.wait, 5)
        except subprocess.TimeoutExpired:
            self.server.process.kill()
            try:
                await asyncio.to_thread(self.server.process.wait, 1)
            except Exception:
                pass

        if self._reader_task:
            self._reader_task.cancel()
            try:
                await asyncio.wait_for(self._reader_task, timeout=1.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass

        for future in self._pending_requests.values():
            if not future.done():
                future.cancel()
        self._pending_requests.clear()
        for waiters in self._diag_waiters.values():
            for waiter in waiters:
                if waiter.task:
                    waiter.task.cancel()
        self._diag_waiters.clear()

        log.info("shutdown complete", {"server_id": self.server_id})
