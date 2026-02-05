"""LSP manager implementation.

This module provides the main LSP interface for managing language server
connections and accessing their features.
"""

import asyncio
import os
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Set
from pydantic import BaseModel

from ..core.bus import Bus, BusEvent
from ..core.config import ConfigManager
from ..project.instance import Instance
from ..util.log import Log
from .client import LSPClient, LSPDiagnostic
from .server import ALL_SERVERS, LSPServerInfo

log = Log.create({"service": "lsp"})


class LSPUpdatedProps(BaseModel):
    """Properties for LSP updated event."""
    pass


# Event for LSP state updates
LSPUpdated = BusEvent.define("lsp.updated", LSPUpdatedProps)


class LSPRange(BaseModel):
    """LSP range definition.

    Attributes:
        start: Start position (line, character)
        end: End position (line, character)
    """
    start: Dict[str, int]
    end: Dict[str, int]


class LSPSymbol(BaseModel):
    """LSP symbol definition.

    Attributes:
        name: Symbol name
        kind: Symbol kind (numeric)
        location: Symbol location (uri, range)
    """
    name: str
    kind: int
    location: Dict[str, Any]


class LSPDocumentSymbol(BaseModel):
    """LSP document symbol definition.

    Attributes:
        name: Symbol name
        detail: Optional detail string
        kind: Symbol kind (numeric)
        range: Symbol range
        selection_range: Selection range
    """
    name: str
    detail: Optional[str] = None
    kind: int
    range: Dict[str, Any]
    selection_range: Dict[str, Any]


class LSPStatus(BaseModel):
    """LSP server status.

    Attributes:
        id: Server ID
        name: Server name
        root: Project root (relative path)
        status: Connection status
    """
    id: str
    name: str
    root: str
    status: Literal["connected", "error"]


class LSPState:
    """State container for LSP clients."""

    def __init__(self):
        self.clients: List[LSPClient] = []
        self.servers: Dict[str, LSPServerInfo] = {}
        self.broken: Set[str] = set()
        self.spawning: Dict[str, asyncio.Task] = {}


# Global state
_state: Optional[LSPState] = None


class LSP:
    """LSP manager.

    Provides methods for managing LSP server connections and
    accessing their features like diagnostics, hover, and navigation.
    """

    @classmethod
    async def _get_state(cls) -> LSPState:
        """Get or initialize the LSP state.

        Returns:
            LSPState instance
        """
        global _state
        if _state is None:
            _state = LSPState()
            await cls._init_servers()
        return _state

    @classmethod
    async def _init_servers(cls) -> None:
        """Initialize available LSP servers from configuration."""
        state = _state
        if not state:
            return

        config = await ConfigManager.get()

        # Check if LSP is disabled globally
        if config.lsp is False:
            log.info("all LSPs are disabled")
            return

        # Add built-in servers
        for server_id, server in ALL_SERVERS.items():
            state.servers[server_id] = server

        # Process custom LSP configuration
        lsp_config = config.lsp if isinstance(config.lsp, dict) else {}

        for name, item in lsp_config.items():
            if not isinstance(item, dict):
                continue

            if item.get("disabled"):
                log.info(f"LSP server {name} is disabled")
                if name in state.servers:
                    del state.servers[name]
                continue

            # Custom server configuration
            existing = state.servers.get(name)
            command = item.get("command", [])
            extensions = item.get("extensions", existing.extensions if existing else [])
            env = item.get("env", {})
            initialization = item.get("initialization", {})

            if command:
                import subprocess

                async def custom_root(file: str) -> Optional[str]:
                    return Instance.directory()

                async def custom_spawn(root: str) -> Optional[Any]:
                    from .server import LSPServerHandle
                    process = subprocess.Popen(
                        command,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        cwd=root,
                        env={**os.environ, **env},
                    )
                    return LSPServerHandle(process, initialization)

                state.servers[name] = LSPServerInfo(
                    server_id=name,
                    extensions=extensions,
                    root=existing.root if existing else custom_root,
                    spawn=custom_spawn,
                )

        log.info("enabled LSP servers", {
            "server_ids": ", ".join(state.servers.keys())
        })

    @classmethod
    async def init(cls) -> None:
        """Initialize LSP manager."""
        await cls._get_state()

    @classmethod
    async def status(cls) -> List[LSPStatus]:
        """Get status of all connected LSP servers.

        Returns:
            List of server status objects
        """
        state = await cls._get_state()
        result: List[LSPStatus] = []

        for client in state.clients:
            server = state.servers.get(client.server_id)
            if server:
                result.append(LSPStatus(
                    id=client.server_id,
                    name=server.id,
                    root=os.path.relpath(client.root, Instance.directory()),
                    status="connected",
                ))

        return result

    @classmethod
    async def _get_clients(cls, file: str) -> List[LSPClient]:
        """Get or create LSP clients for a file.

        Args:
            file: File path

        Returns:
            List of applicable LSP clients
        """
        state = await cls._get_state()
        extension = os.path.splitext(file)[1] or file
        result: List[LSPClient] = []

        async def schedule(
            server: LSPServerInfo,
            root: str,
            key: str
        ) -> Optional[LSPClient]:
            """Schedule spawning of an LSP server."""
            try:
                handle = await server.spawn(root)
                if not handle:
                    state.broken.add(key)
                    return None

                log.info("spawned LSP server", {"server_id": server.id})

                client = LSPClient(
                    server_id=server.id,
                    server=handle,
                    root=root,
                )

                if not await client.initialize():
                    state.broken.add(key)
                    handle.process.kill()
                    return None

                # Check if another client was created while we were spawning
                existing = next(
                    (c for c in state.clients
                     if c.root == root and c.server_id == server.id),
                    None
                )
                if existing:
                    handle.process.kill()
                    return existing

                state.clients.append(client)
                return client

            except Exception as e:
                state.broken.add(key)
                log.error(f"Failed to spawn LSP server {server.id}", {
                    "error": str(e)
                })
                return None

        for server in state.servers.values():
            # Check if server handles this extension
            if server.extensions and extension not in server.extensions:
                continue

            # Find project root
            root = await server.root(file)
            if not root:
                continue

            key = root + server.id
            if key in state.broken:
                continue

            # Check for existing client
            existing = next(
                (c for c in state.clients
                 if c.root == root and c.server_id == server.id),
                None
            )
            if existing:
                result.append(existing)
                continue

            # Check for in-flight spawn
            if key in state.spawning:
                client = await state.spawning[key]
                if client:
                    result.append(client)
                continue

            # Spawn new client
            task = asyncio.create_task(schedule(server, root, key))
            state.spawning[key] = task

            try:
                client = await task
                if client:
                    result.append(client)
                    await Bus.publish(LSPUpdated, LSPUpdatedProps())
            finally:
                state.spawning.pop(key, None)

        return result

    @classmethod
    async def has_clients(cls, file: str) -> bool:
        """Check if any LSP servers can handle a file.

        Args:
            file: File path

        Returns:
            True if at least one server can handle the file
        """
        state = await cls._get_state()
        extension = os.path.splitext(file)[1] or file

        for server in state.servers.values():
            if server.extensions and extension not in server.extensions:
                continue

            root = await server.root(file)
            if not root:
                continue

            key = root + server.id
            if key in state.broken:
                continue

            return True

        return False

    @classmethod
    async def touch_file(
        cls,
        file: str,
        wait_for_diagnostics: bool = False
    ) -> None:
        """Notify LSP servers that a file was modified.

        Args:
            file: File path
            wait_for_diagnostics: Whether to wait for diagnostics
        """
        log.info("touching file", {"file": file})
        clients = await cls._get_clients(file)

        async def process_client(client: LSPClient) -> None:
            if wait_for_diagnostics:
                wait_task = client.wait_for_diagnostics(file)
            else:
                wait_task = asyncio.sleep(0)

            await client.open_file(file)
            await wait_task

        try:
            await asyncio.gather(*[process_client(c) for c in clients])
        except Exception as e:
            log.error("failed to touch file", {"file": file, "error": str(e)})

    @classmethod
    async def diagnostics(cls) -> Dict[str, List[LSPDiagnostic]]:
        """Get all diagnostics from all connected servers.

        Returns:
            Dictionary of file path to diagnostics
        """
        state = await cls._get_state()
        results: Dict[str, List[LSPDiagnostic]] = {}

        for client in state.clients:
            for path, diags in client.diagnostics.items():
                if path not in results:
                    results[path] = []
                results[path].extend(diags)

        return results

    @classmethod
    async def hover(
        cls,
        file: str,
        line: int,
        character: int
    ) -> List[Any]:
        """Get hover information at a position.

        Args:
            file: File path
            line: Line number (0-indexed)
            character: Character position (0-indexed)

        Returns:
            List of hover results from all applicable servers
        """
        clients = await cls._get_clients(file)
        results = []

        for client in clients:
            try:
                result = await client._send_request("textDocument/hover", {
                    "textDocument": {"uri": client._path_to_uri(file)},
                    "position": {"line": line, "character": character},
                })
                if result:
                    results.append(result)
            except Exception:
                pass

        return results

    @classmethod
    async def definition(
        cls,
        file: str,
        line: int,
        character: int
    ) -> List[Any]:
        """Get definition locations for a symbol.

        Args:
            file: File path
            line: Line number (0-indexed)
            character: Character position (0-indexed)

        Returns:
            List of definition locations
        """
        clients = await cls._get_clients(file)
        results = []

        for client in clients:
            try:
                result = await client._send_request("textDocument/definition", {
                    "textDocument": {"uri": client._path_to_uri(file)},
                    "position": {"line": line, "character": character},
                })
                if result:
                    if isinstance(result, list):
                        results.extend(result)
                    else:
                        results.append(result)
            except Exception:
                pass

        return results

    @classmethod
    async def references(
        cls,
        file: str,
        line: int,
        character: int
    ) -> List[Any]:
        """Get all references to a symbol.

        Args:
            file: File path
            line: Line number (0-indexed)
            character: Character position (0-indexed)

        Returns:
            List of reference locations
        """
        clients = await cls._get_clients(file)
        results = []

        for client in clients:
            try:
                result = await client._send_request("textDocument/references", {
                    "textDocument": {"uri": client._path_to_uri(file)},
                    "position": {"line": line, "character": character},
                    "context": {"includeDeclaration": True},
                })
                if result:
                    results.extend(result)
            except Exception:
                pass

        return results

    @classmethod
    async def workspace_symbol(cls, query: str) -> List[LSPSymbol]:
        """Search for symbols in the workspace.

        Args:
            query: Search query

        Returns:
            List of matching symbols
        """
        state = await cls._get_state()
        results: List[LSPSymbol] = []

        # Symbol kinds to include
        relevant_kinds = {5, 6, 11, 12, 13, 14, 23, 10}  # Class, Method, Interface, Function, Variable, Constant, Struct, Enum

        for client in state.clients:
            try:
                result = await client._send_request("workspace/symbol", {
                    "query": query
                })
                if result:
                    for item in result:
                        if item.get("kind") in relevant_kinds:
                            results.append(LSPSymbol.model_validate(item))
            except Exception:
                pass

        return results[:10]  # Limit results

    @classmethod
    async def document_symbol(cls, uri: str) -> List[Any]:
        """Get symbols in a document.

        Args:
            uri: Document URI

        Returns:
            List of document symbols
        """
        from urllib.parse import urlparse, unquote

        parsed = urlparse(uri)
        file = unquote(parsed.path)
        if os.name == "nt" and file.startswith("/"):
            file = file[1:]

        clients = await cls._get_clients(file)
        results = []

        for client in clients:
            try:
                result = await client._send_request("textDocument/documentSymbol", {
                    "textDocument": {"uri": uri}
                })
                if result:
                    results.extend(result)
            except Exception:
                pass

        return [r for r in results if r]

    @classmethod
    async def shutdown(cls) -> None:
        """Shutdown all LSP clients."""
        global _state
        if _state:
            for client in _state.clients:
                try:
                    await client.shutdown()
                except Exception as e:
                    log.error("Failed to shutdown LSP client", {"error": str(e)})
            _state = None

    @classmethod
    def format_diagnostic(cls, diagnostic: LSPDiagnostic) -> str:
        """Format a diagnostic for display.

        Args:
            diagnostic: Diagnostic to format

        Returns:
            Formatted string
        """
        severity_map = {
            1: "ERROR",
            2: "WARN",
            3: "INFO",
            4: "HINT",
        }

        severity = severity_map.get(diagnostic.severity, "ERROR")
        line = diagnostic.range.get("start", {}).get("line", 0) + 1
        col = diagnostic.range.get("start", {}).get("character", 0) + 1

        return f"{severity} [{line}:{col}] {diagnostic.message}"
