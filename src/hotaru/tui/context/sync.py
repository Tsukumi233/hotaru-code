"""Sync context for data synchronization.

This module provides synchronized state management for sessions,
messages, providers, agents, and other data from the backend.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any, Callable, Set
from contextvars import ContextVar

from ...util.log import Log

log = Log.create({"service": "tui.context.sync"})


class SyncEvent:
    """Canonical sync event names for runtime subscriptions."""

    STATUS_UPDATED = "status.updated"
    PROVIDERS_UPDATED = "providers.updated"
    AGENTS_UPDATED = "agents.updated"
    CONFIG_UPDATED = "config.updated"
    SESSIONS_UPDATED = "sessions.updated"
    SESSION_STATUS_UPDATED = "session.status.updated"
    MESSAGES_UPDATED = "messages.updated"
    PERMISSION_UPDATED = "permission.updated"
    QUESTION_UPDATED = "question.updated"
    MCP_UPDATED = "mcp.updated"
    LSP_UPDATED = "lsp.updated"


@dataclass
class SyncData:
    """Synchronized data store.

    Contains all data synchronized from the backend.
    """
    # Status
    status: str = "loading"  # loading, partial, complete

    # Providers and models
    providers: List[Dict[str, Any]] = field(default_factory=list)
    provider_defaults: Dict[str, str] = field(default_factory=dict)

    # Agents
    agents: List[Dict[str, Any]] = field(default_factory=list)

    # Configuration
    config: Dict[str, Any] = field(default_factory=dict)

    # Sessions
    sessions: List[Dict[str, Any]] = field(default_factory=list)
    session_status: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Messages and parts
    messages: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    parts: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)

    # Permissions and questions
    permissions: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    questions: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)

    # MCP and LSP status
    mcp: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    lsp: List[Dict[str, Any]] = field(default_factory=list)

    # Paths
    paths: Dict[str, str] = field(default_factory=dict)


class SyncContext:
    """Sync context for data synchronization.

    Manages synchronized state from the backend and provides
    methods for accessing and updating data.
    """

    def __init__(self) -> None:
        """Initialize sync context."""
        self._data = SyncData()
        self._listeners: Dict[str, List[Callable[[Any], None]]] = {}
        self._synced_sessions: Set[str] = set()

    @staticmethod
    def _session_sort_key(session: Dict[str, Any]) -> int:
        """Build a descending sort key for session recency."""
        updated = session.get("time", {}).get("updated")
        if isinstance(updated, (int, float)):
            return int(updated)
        return 0

    @property
    def data(self) -> SyncData:
        """Get the synchronized data."""
        return self._data

    @property
    def status(self) -> str:
        """Get sync status."""
        return self._data.status

    @property
    def ready(self) -> bool:
        """Check if sync is ready (not loading)."""
        return self._data.status != "loading"

    def set_status(self, status: str) -> None:
        """Set sync status.

        Args:
            status: New status (loading, partial, complete)
        """
        self._data.status = status
        self._notify("status", status)
        self._notify(SyncEvent.STATUS_UPDATED, status)

    # Provider methods
    def set_providers(self, providers: List[Dict[str, Any]]) -> None:
        """Set providers list."""
        self._data.providers = providers
        self._notify("providers", providers)
        self._notify(SyncEvent.PROVIDERS_UPDATED, providers)

    def set_provider_defaults(self, defaults: Dict[str, str]) -> None:
        """Set provider defaults."""
        self._data.provider_defaults = defaults

    # Agent methods
    def set_agents(self, agents: List[Dict[str, Any]]) -> None:
        """Set agents list."""
        self._data.agents = agents
        self._notify("agents", agents)
        self._notify(SyncEvent.AGENTS_UPDATED, agents)

    # Config methods
    def set_config(self, config: Dict[str, Any]) -> None:
        """Set configuration."""
        self._data.config = config
        self._notify("config", config)
        self._notify(SyncEvent.CONFIG_UPDATED, config)

    # Session methods
    def set_sessions(self, sessions: List[Dict[str, Any]]) -> None:
        """Set sessions list."""
        self._data.sessions = sorted(
            sessions,
            key=self._session_sort_key,
            reverse=True,
        )
        self._notify("sessions", self._data.sessions)
        self._notify(SyncEvent.SESSIONS_UPDATED, self._data.sessions)

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get a session by ID.

        Args:
            session_id: Session ID

        Returns:
            Session data or None
        """
        for session in self._data.sessions:
            if session.get("id") == session_id:
                return session
        return None

    def update_session(self, session: Dict[str, Any]) -> None:
        """Update or add a session.

        Args:
            session: Session data
        """
        session_id = session.get("id")
        if not session_id:
            return

        # Find and update or insert
        for i, s in enumerate(self._data.sessions):
            if s.get("id") == session_id:
                self._data.sessions[i] = session
                self._data.sessions.sort(
                    key=self._session_sort_key,
                    reverse=True,
                )
                self._notify("session.updated", session)
                return

        # Insert in sorted order
        self._data.sessions.append(session)
        self._data.sessions.sort(
            key=self._session_sort_key,
            reverse=True,
        )
        self._notify("session.updated", session)

    def delete_session(self, session_id: str) -> None:
        """Delete a session.

        Args:
            session_id: Session ID to delete
        """
        self._data.sessions = [
            s for s in self._data.sessions
            if s.get("id") != session_id
        ]
        self._notify("session.deleted", session_id)

    def set_session_status(self, session_id: str, status: Dict[str, Any]) -> None:
        """Set session status.

        Args:
            session_id: Session ID
            status: Status data
        """
        self._data.session_status[session_id] = status
        self._notify("session.status", {"session_id": session_id, "status": status})
        self._notify(SyncEvent.SESSION_STATUS_UPDATED, {"session_id": session_id, "status": status})

    # Message methods
    def get_messages(self, session_id: str) -> List[Dict[str, Any]]:
        """Get messages for a session.

        Args:
            session_id: Session ID

        Returns:
            List of messages
        """
        return self._data.messages.get(session_id, [])

    def set_messages(self, session_id: str, messages: List[Dict[str, Any]]) -> None:
        """Set messages for a session.

        Args:
            session_id: Session ID
            messages: List of messages
        """
        self._data.messages[session_id] = messages
        self._notify("messages", {"session_id": session_id, "messages": messages})
        self._notify(SyncEvent.MESSAGES_UPDATED, {"session_id": session_id, "messages": messages})

    def add_message(self, session_id: str, message: Dict[str, Any]) -> None:
        """Add a message to a session.

        Args:
            session_id: Session ID
            message: Message data
        """
        if session_id not in self._data.messages:
            self._data.messages[session_id] = []

        messages = self._data.messages[session_id]
        message_id = message.get("id")

        # Update existing or append
        for i, m in enumerate(messages):
            if m.get("id") == message_id:
                messages[i] = message
                self._notify("message.updated", message)
                return

        messages.append(message)
        self._notify("message.updated", message)

    # Part methods
    def get_parts(self, message_id: str) -> List[Dict[str, Any]]:
        """Get parts for a message.

        Args:
            message_id: Message ID

        Returns:
            List of parts
        """
        return self._data.parts.get(message_id, [])

    def set_parts(self, message_id: str, parts: List[Dict[str, Any]]) -> None:
        """Set parts for a message.

        Args:
            message_id: Message ID
            parts: List of parts
        """
        self._data.parts[message_id] = parts

    def add_part(self, message_id: str, part: Dict[str, Any]) -> None:
        """Add a part to a message.

        Args:
            message_id: Message ID
            part: Part data
        """
        if message_id not in self._data.parts:
            self._data.parts[message_id] = []

        parts = self._data.parts[message_id]
        part_id = part.get("id")

        # Update existing or append
        for i, p in enumerate(parts):
            if p.get("id") == part_id:
                parts[i] = part
                return

        parts.append(part)

    # Permission methods
    def get_permissions(self, session_id: str) -> List[Dict[str, Any]]:
        """Get pending permissions for a session."""
        return self._data.permissions.get(session_id, [])

    def add_permission(self, session_id: str, permission: Dict[str, Any]) -> None:
        """Add a permission request."""
        if session_id not in self._data.permissions:
            self._data.permissions[session_id] = []
        self._data.permissions[session_id].append(permission)
        self._notify("permission.asked", permission)
        self._notify(SyncEvent.PERMISSION_UPDATED, {"session_id": session_id})

    def remove_permission(self, session_id: str, request_id: str) -> None:
        """Remove a permission request."""
        if session_id in self._data.permissions:
            self._data.permissions[session_id] = [
                p for p in self._data.permissions[session_id]
                if p.get("id") != request_id
            ]
            self._notify("permission.replied", {"session_id": session_id, "request_id": request_id})
            self._notify(SyncEvent.PERMISSION_UPDATED, {"session_id": session_id})

    # Question methods
    def get_questions(self, session_id: str) -> List[Dict[str, Any]]:
        """Get pending questions for a session."""
        return self._data.questions.get(session_id, [])

    def add_question(self, session_id: str, question: Dict[str, Any]) -> None:
        """Add a question request."""
        if session_id not in self._data.questions:
            self._data.questions[session_id] = []
        self._data.questions[session_id].append(question)
        self._notify("question.asked", question)
        self._notify(SyncEvent.QUESTION_UPDATED, {"session_id": session_id})

    def remove_question(self, session_id: str, request_id: str) -> None:
        """Remove a question request."""
        if session_id in self._data.questions:
            self._data.questions[session_id] = [
                q for q in self._data.questions[session_id]
                if q.get("id") != request_id
            ]
            self._notify(SyncEvent.QUESTION_UPDATED, {"session_id": session_id})

    # MCP methods
    def set_mcp_status(self, mcp: Dict[str, Dict[str, Any]]) -> None:
        """Set MCP status."""
        self._data.mcp = mcp
        self._notify("mcp", mcp)
        self._notify(SyncEvent.MCP_UPDATED, mcp)

    # LSP methods
    def set_lsp_status(self, lsp: List[Dict[str, Any]]) -> None:
        """Set LSP status."""
        self._data.lsp = lsp
        self._notify("lsp", lsp)
        self._notify(SyncEvent.LSP_UPDATED, lsp)

    # Path methods
    def set_paths(self, paths: Dict[str, str]) -> None:
        """Set paths."""
        self._data.paths = paths

    # Session sync
    async def sync_session(self, session_id: str, sdk: Any, force: bool = False) -> None:
        """Sync a session's full data through the SDK/API boundary.

        Args:
            session_id: Session ID to sync
            sdk: SDK context instance used for API-boundary reads
            force: If True, re-sync even if already synced
        """
        if not force and session_id in self._synced_sessions:
            return

        # Load session info via API boundary.
        session = await sdk.get_session(session_id)
        if session:
            self.update_session(session)

        # Load messages via API boundary.
        messages = await sdk.get_messages(session_id)
        self.set_messages(session_id, messages)

        # Mark as synced
        self._synced_sessions.add(session_id)
        log.debug("synced session", {
            "session_id": session_id,
            "message_count": len(messages),
        })

    def is_session_synced(self, session_id: str) -> bool:
        """Check if a session has been fully synced."""
        return session_id in self._synced_sessions

    # Listener methods
    def on(self, event: str, callback: Callable[[Any], None]) -> Callable[[], None]:
        """Register an event listener.

        Args:
            event: Event name
            callback: Callback function

        Returns:
            Unsubscribe function
        """
        if event not in self._listeners:
            self._listeners[event] = []
        self._listeners[event].append(callback)

        def unsubscribe():
            if event in self._listeners and callback in self._listeners[event]:
                self._listeners[event].remove(callback)

        return unsubscribe

    def _notify(self, event: str, data: Any) -> None:
        """Notify listeners of an event.

        Args:
            event: Event name
            data: Event data
        """
        if event in self._listeners:
            for listener in self._listeners[event]:
                try:
                    listener(data)
                except Exception as e:
                    log.error("sync listener error", {"event": event, "error": str(e)})


# Context variable
_sync_context: ContextVar[Optional[SyncContext]] = ContextVar(
    "sync_context",
    default=None
)


class SyncProvider:
    """Provider for sync context."""

    _instance: Optional[SyncContext] = None

    @classmethod
    def get(cls) -> SyncContext:
        """Get the current sync context."""
        ctx = _sync_context.get()
        if ctx is None:
            ctx = SyncContext()
            _sync_context.set(ctx)
            cls._instance = ctx
        return ctx

    @classmethod
    def provide(cls) -> SyncContext:
        """Create and provide sync context.

        Returns:
            The sync context
        """
        ctx = SyncContext()
        _sync_context.set(ctx)
        cls._instance = ctx
        return ctx

    @classmethod
    def reset(cls) -> None:
        """Reset the sync context."""
        _sync_context.set(None)
        cls._instance = None


def use_sync() -> SyncContext:
    """Hook to access sync context."""
    return SyncProvider.get()
