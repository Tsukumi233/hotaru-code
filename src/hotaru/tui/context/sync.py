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
    MESSAGE_UPDATED = "message.updated"
    PART_UPDATED = "part.updated"
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

    @staticmethod
    def _message_sort_key(message: Dict[str, Any]) -> str:
        """Build an ascending sort key for message order."""
        return str(message.get("id") or "")

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
        normalized: List[Dict[str, Any]] = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            payload = self._normalize_message_payload(session_id, message)
            normalized.append(payload)
            message_id = str(payload.get("id") or "")
            if message_id:
                self._data.parts[message_id] = payload["parts"]

        self._data.messages[session_id] = normalized
        self._synced_sessions.add(session_id)
        self._notify("messages", {"session_id": session_id, "messages": normalized})
        self._notify(SyncEvent.MESSAGES_UPDATED, {"session_id": session_id, "messages": normalized})

    def _normalize_message_payload(self, session_id: str, message: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize runtime message/event payloads into renderable message shape."""
        info_raw = message.get("info")
        info: Dict[str, Any]
        if isinstance(info_raw, dict):
            info = dict(info_raw)
        else:
            info = dict(message)

        if session_id and not info.get("session_id"):
            info["session_id"] = session_id

        message_id = str(message.get("id") or info.get("id") or "")
        role = str(message.get("role") or info.get("role") or "assistant")

        parts: List[Dict[str, Any]] = []
        raw_parts = message.get("parts")
        if isinstance(raw_parts, list):
            for part in raw_parts:
                if isinstance(part, dict):
                    parts.append(dict(part))
        parts.sort(key=self._message_sort_key)

        payload: Dict[str, Any] = {
            "id": message_id,
            "role": role,
            "info": info,
            "parts": parts,
        }
        metadata = message.get("metadata")
        if isinstance(metadata, dict):
            payload["metadata"] = dict(metadata)
        return payload

    def _ensure_message_payload(self, session_id: str, message_id: str, role: str = "assistant") -> Dict[str, Any]:
        """Ensure a message shell exists so part-first streams can render incrementally."""
        if session_id not in self._data.messages:
            self._data.messages[session_id] = []

        messages = self._data.messages[session_id]
        for message in messages:
            if str(message.get("id") or "") == message_id:
                return message

        shell = {
            "id": message_id,
            "role": role,
            "info": {
                "id": message_id,
                "role": role,
                "session_id": session_id,
            },
            "parts": [],
        }
        messages.append(shell)
        messages.sort(key=self._message_sort_key)
        self._data.parts[message_id] = shell["parts"]
        return shell

    def add_message(self, session_id: str, message: Dict[str, Any]) -> None:
        """Add a message to a session.

        Args:
            session_id: Session ID
            message: Message data
        """
        payload = self._normalize_message_payload(session_id, message)
        message_id = str(payload.get("id") or "")
        if not message_id:
            return

        messages = self._data.messages.setdefault(session_id, [])
        existing_index = -1
        for i, current in enumerate(messages):
            if str(current.get("id") or "") == message_id:
                existing_index = i
                break

        if existing_index >= 0:
            existing = messages[existing_index]
            merged = dict(existing)
            merged.update(payload)
            if "metadata" not in payload and "metadata" in existing:
                merged["metadata"] = existing["metadata"]
            if not payload.get("parts"):
                merged["parts"] = existing.get("parts", [])
            messages[existing_index] = merged
            payload = merged
        else:
            messages.append(payload)
            messages.sort(key=self._message_sort_key)

        parts_ref = payload.get("parts")
        if not isinstance(parts_ref, list):
            parts_ref = []
            payload["parts"] = parts_ref
        self._data.parts[message_id] = parts_ref

        self._notify(SyncEvent.MESSAGE_UPDATED, {"session_id": session_id, "message": payload})
        self._notify("messages", {"session_id": session_id, "messages": messages})
        self._notify(SyncEvent.MESSAGES_UPDATED, {"session_id": session_id, "messages": messages})

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
        session_id = str(part.get("session_id") or "")
        role = "assistant"
        existing_message = self._find_message(message_id)
        if existing_message is not None:
            role = str(existing_message.get("role") or role)
            info = existing_message.get("info", {})
            if isinstance(info, dict):
                session_id = str(info.get("session_id") or session_id)
        if not session_id:
            return

        message = self._ensure_message_payload(session_id, message_id, role=role)
        parts = message.setdefault("parts", [])
        if not isinstance(parts, list):
            parts = []
            message["parts"] = parts
        self._data.parts[message_id] = parts
        part_id = part.get("id")

        # Update existing or append
        for i, p in enumerate(parts):
            if p.get("id") == part_id:
                parts[i] = dict(part)
                self._notify(
                    SyncEvent.PART_UPDATED,
                    {"session_id": session_id, "message_id": message_id, "part": parts[i]},
                )
                self._notify("messages", {"session_id": session_id, "messages": self._data.messages[session_id]})
                self._notify(
                    SyncEvent.MESSAGES_UPDATED,
                    {"session_id": session_id, "messages": self._data.messages[session_id]},
                )
                return

        added = dict(part)
        parts.append(added)
        parts.sort(key=self._message_sort_key)
        self._notify(
            SyncEvent.PART_UPDATED,
            {"session_id": session_id, "message_id": message_id, "part": added},
        )
        self._notify("messages", {"session_id": session_id, "messages": self._data.messages[session_id]})
        self._notify(
            SyncEvent.MESSAGES_UPDATED,
            {"session_id": session_id, "messages": self._data.messages[session_id]},
        )

    def apply_part_delta(
        self,
        *,
        session_id: str,
        message_id: str,
        part_id: str,
        field: str,
        delta: str,
    ) -> None:
        """Apply part delta updates from runtime events."""
        if not session_id or not message_id or not part_id or not field:
            return
        message = self._ensure_message_payload(session_id, message_id, role="assistant")
        parts = message.setdefault("parts", [])
        if not isinstance(parts, list):
            parts = []
            message["parts"] = parts
        self._data.parts[message_id] = parts

        target: Optional[Dict[str, Any]] = None
        for part in parts:
            if str(part.get("id") or "") == part_id:
                target = part
                break

        if target is None:
            target = {
                "id": part_id,
                "session_id": session_id,
                "message_id": message_id,
                "type": "text",
                field: "",
            }
            parts.append(target)
            parts.sort(key=self._message_sort_key)

        existing = target.get(field)
        target[field] = f"{existing if isinstance(existing, str) else ''}{delta}"

        self._notify(
            SyncEvent.PART_UPDATED,
            {"session_id": session_id, "message_id": message_id, "part": target},
        )
        self._notify("messages", {"session_id": session_id, "messages": self._data.messages[session_id]})
        self._notify(
            SyncEvent.MESSAGES_UPDATED,
            {"session_id": session_id, "messages": self._data.messages[session_id]},
        )

    def _find_message(self, message_id: str) -> Optional[Dict[str, Any]]:
        for messages in self._data.messages.values():
            for message in messages:
                if str(message.get("id") or "") == message_id:
                    return message
        return None

    def apply_runtime_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Reduce runtime SDK events into the sync store."""
        if event_type == "message.updated":
            info = data.get("info")
            if not isinstance(info, dict):
                return
            session_id = str(info.get("session_id") or "")
            if not session_id:
                return
            self.add_message(session_id, info)
            return

        if event_type == "message.part.updated":
            part = data.get("part")
            if not isinstance(part, dict):
                return
            session_id = str(part.get("session_id") or "")
            message_id = str(part.get("message_id") or "")
            if not session_id or not message_id:
                return
            self.add_part(message_id, part)
            return

        if event_type == "message.part.delta":
            session_id = str(data.get("session_id") or "")
            message_id = str(data.get("message_id") or "")
            part_id = str(data.get("part_id") or "")
            field = str(data.get("field") or "")
            delta = str(data.get("delta") or "")
            self.apply_part_delta(
                session_id=session_id,
                message_id=message_id,
                part_id=part_id,
                field=field,
                delta=delta,
            )
            return

        if event_type == "session.status":
            session_id = str(data.get("session_id") or "")
            status = data.get("status")
            if not session_id or not isinstance(status, dict):
                return
            self.set_session_status(session_id, status)

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
