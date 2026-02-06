"""Session management.

Sessions track conversations between users and AI agents.
Persisted via the hierarchical JSON file storage layer.
"""

import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ..core.bus import Bus, BusEvent
from ..core.id import Identifier
from ..storage import Storage, NotFoundError
from ..util.log import Log
from .message import MessageInfo

log = Log.create({"service": "session"})


class SessionTime(BaseModel):
    """Session timing information."""
    created: int
    updated: int


class SessionShare(BaseModel):
    """Session sharing information."""
    url: str
    version: int


class SessionInfo(BaseModel):
    """Session information."""
    id: str
    project_id: str
    title: Optional[str] = None
    agent: str = "build"
    model_id: Optional[str] = None
    provider_id: Optional[str] = None
    directory: Optional[str] = None
    parent_id: Optional[str] = None
    time: SessionTime
    share: Optional[SessionShare] = None

    class Config:
        extra = "allow"


# Session events
class SessionCreatedProperties(BaseModel):
    """Properties for session created event."""
    session: SessionInfo


class SessionUpdatedProperties(BaseModel):
    """Properties for session updated event."""
    session: SessionInfo


class SessionDeletedProperties(BaseModel):
    """Properties for session deleted event."""
    session_id: str


SessionCreated = BusEvent(
    event_type="session.created",
    properties_type=SessionCreatedProperties
)

SessionUpdated = BusEvent(
    event_type="session.updated",
    properties_type=SessionUpdatedProperties
)

SessionDeleted = BusEvent(
    event_type="session.deleted",
    properties_type=SessionDeletedProperties
)


class Session:
    """Session management.

    Sessions are persistent conversations that track messages between
    users and AI agents.  Data is stored on disk via ``Storage``.
    """

    # Storage key helpers
    @staticmethod
    def _session_key(project_id: str, session_id: str) -> List[str]:
        return ["session", project_id, session_id]

    @staticmethod
    def _message_key(session_id: str, message_id: str) -> List[str]:
        return ["message", session_id, message_id]

    @classmethod
    async def create(
        cls,
        project_id: str,
        agent: str = "build",
        directory: Optional[str] = None,
        model_id: Optional[str] = None,
        provider_id: Optional[str] = None,
        parent_id: Optional[str] = None
    ) -> SessionInfo:
        """Create a new session.

        Args:
            project_id: Project ID
            agent: Agent name
            directory: Working directory
            model_id: Model ID
            provider_id: Provider ID
            parent_id: Parent session ID (for forks)

        Returns:
            Created session info
        """
        now = int(time.time() * 1000)
        session_id = Identifier.ascending("session")

        session = SessionInfo(
            id=session_id,
            project_id=project_id,
            agent=agent,
            directory=directory,
            model_id=model_id,
            provider_id=provider_id,
            parent_id=parent_id,
            time=SessionTime(created=now, updated=now)
        )

        await Storage.write(
            cls._session_key(project_id, session_id),
            session.model_dump(),
        )

        log.info("created session", {"session_id": session_id, "project_id": project_id})

        await Bus.publish(SessionCreated, SessionCreatedProperties(session=session))

        return session

    @classmethod
    async def get(cls, session_id: str, project_id: Optional[str] = None) -> Optional[SessionInfo]:
        """Get a session by ID.

        If *project_id* is not given the method scans all projects
        under the ``session/`` prefix (slightly slower).

        Args:
            session_id: Session ID
            project_id: Optional project ID for direct lookup

        Returns:
            SessionInfo or None
        """
        if project_id:
            try:
                data = await Storage.read(cls._session_key(project_id, session_id))
                return SessionInfo.model_validate(data)
            except NotFoundError:
                return None

        # Scan all projects
        keys = await Storage.list(["session"])
        for key in keys:
            # key looks like ["session", project_id, session_id]
            if len(key) >= 3 and key[-1] == session_id:
                try:
                    data = await Storage.read(key)
                    return SessionInfo.model_validate(data)
                except NotFoundError:
                    continue
        return None

    @classmethod
    async def list(cls, project_id: str) -> List[SessionInfo]:
        """List sessions for a project.

        Args:
            project_id: Project ID

        Returns:
            List of sessions, newest first
        """
        keys = await Storage.list(["session", project_id])
        sessions: List[SessionInfo] = []
        for key in keys:
            try:
                data = await Storage.read(key)
                sessions.append(SessionInfo.model_validate(data))
            except (NotFoundError, Exception):
                continue
        return sorted(sessions, key=lambda s: s.time.updated, reverse=True)

    @classmethod
    async def update(
        cls,
        session_id: str,
        project_id: Optional[str] = None,
        title: Optional[str] = None,
        agent: Optional[str] = None,
        model_id: Optional[str] = None,
        provider_id: Optional[str] = None
    ) -> Optional[SessionInfo]:
        """Update a session.

        Args:
            session_id: Session ID
            project_id: Project ID (required for direct lookup)
            title: New title
            agent: New agent
            model_id: New model ID
            provider_id: New provider ID

        Returns:
            Updated session or None
        """
        # Look up the session to find its project_id
        session = await cls.get(session_id, project_id=project_id)
        if not session:
            return None

        def _mutate(data: dict):
            if title is not None:
                data["title"] = title
            if agent is not None:
                data["agent"] = agent
            if model_id is not None:
                data["model_id"] = model_id
            if provider_id is not None:
                data["provider_id"] = provider_id
            data["time"]["updated"] = int(time.time() * 1000)

        try:
            updated = await Storage.update(
                cls._session_key(session.project_id, session_id),
                _mutate,
            )
            result = SessionInfo.model_validate(updated)
        except NotFoundError:
            return None

        log.info("updated session", {"session_id": session_id})
        await Bus.publish(SessionUpdated, SessionUpdatedProperties(session=result))
        return result

    @classmethod
    async def delete(cls, session_id: str, project_id: Optional[str] = None) -> bool:
        """Delete a session and all its messages.

        Args:
            session_id: Session ID
            project_id: Project ID (looked up if not given)

        Returns:
            True if deleted
        """
        session = await cls.get(session_id, project_id=project_id)
        if not session:
            return False

        # Delete child sessions recursively
        all_sessions = await cls.list(session.project_id)
        for s in all_sessions:
            if s.parent_id == session_id:
                await cls.delete(s.id, project_id=session.project_id)

        # Delete all messages for this session
        msg_keys = await Storage.list(["message", session_id])
        for key in msg_keys:
            await Storage.remove(key)

        # Delete the session itself
        await Storage.remove(cls._session_key(session.project_id, session_id))

        log.info("deleted session", {"session_id": session_id})
        await Bus.publish(SessionDeleted, SessionDeletedProperties(session_id=session_id))
        return True

    @classmethod
    async def add_message(cls, session_id: str, message: MessageInfo) -> None:
        """Add a message to a session (persisted to disk).

        Args:
            session_id: Session ID
            message: Message to add
        """
        await Storage.write(
            cls._message_key(session_id, message.id),
            message.model_dump(),
        )

        # Touch session timestamp
        session = await cls.get(session_id)
        if session:
            try:
                await Storage.update(
                    cls._session_key(session.project_id, session_id),
                    lambda d: d["time"].__setitem__("updated", int(time.time() * 1000)),
                )
            except NotFoundError:
                pass

    @classmethod
    async def get_messages(cls, session_id: str) -> List[MessageInfo]:
        """Get messages for a session (loaded from disk).

        Args:
            session_id: Session ID

        Returns:
            List of messages, oldest first
        """
        keys = await Storage.list(["message", session_id])
        messages: List[MessageInfo] = []
        for key in keys:
            try:
                data = await Storage.read(key)
                messages.append(MessageInfo.model_validate(data))
            except (NotFoundError, Exception):
                continue
        # Sort by message ID (ascending = chronological)
        messages.sort(key=lambda m: m.id)
        return messages

    @classmethod
    async def fork(
        cls,
        session_id: str,
        from_message_id: Optional[str] = None
    ) -> Optional[SessionInfo]:
        """Fork a session from a specific point.

        Messages are deep-copied so mutations in the fork
        do not affect the original session.

        Args:
            session_id: Session ID to fork
            from_message_id: Message ID to fork from (None = full copy)

        Returns:
            New forked session or None
        """
        session = await cls.get(session_id)
        if not session:
            return None

        messages = await cls.get_messages(session_id)

        # Create new session
        new_session = await cls.create(
            project_id=session.project_id,
            agent=session.agent,
            directory=session.directory,
            model_id=session.model_id,
            provider_id=session.provider_id,
            parent_id=session_id
        )

        # Deep-copy messages up to the fork point
        for msg in messages:
            cloned = msg.model_copy(deep=True)
            # Give the clone a new ID and re-parent it
            cloned_id = Identifier.ascending("message")
            cloned.id = cloned_id
            cloned.metadata.session_id = new_session.id
            await cls.add_message(new_session.id, cloned)
            if from_message_id and msg.id == from_message_id:
                break

        log.info("forked session", {
            "from": session_id,
            "to": new_session.id,
        })

        return new_session

    @classmethod
    def reset(cls) -> None:
        """Reset storage cache (for testing)."""
        Storage.reset()
