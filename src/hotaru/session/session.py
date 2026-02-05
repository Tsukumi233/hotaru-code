"""Session management.

Sessions track conversations between users and AI agents.
"""

import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ..core.bus import Bus, BusEvent
from ..core.id import Identifier
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
    users and AI agents.
    """

    # In-memory session storage (will be replaced with proper storage)
    _sessions: Dict[str, SessionInfo] = {}
    _messages: Dict[str, List[MessageInfo]] = {}

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

        cls._sessions[session_id] = session
        cls._messages[session_id] = []

        log.info("created session", {"session_id": session_id, "project_id": project_id})

        await Bus.publish(SessionCreated, SessionCreatedProperties(session=session))

        return session

    @classmethod
    async def get(cls, session_id: str) -> Optional[SessionInfo]:
        """Get a session by ID.

        Args:
            session_id: Session ID

        Returns:
            SessionInfo or None
        """
        return cls._sessions.get(session_id)

    @classmethod
    async def list(cls, project_id: str) -> List[SessionInfo]:
        """List sessions for a project.

        Args:
            project_id: Project ID

        Returns:
            List of sessions, newest first
        """
        sessions = [
            s for s in cls._sessions.values()
            if s.project_id == project_id
        ]
        return sorted(sessions, key=lambda s: s.time.updated, reverse=True)

    @classmethod
    async def update(
        cls,
        session_id: str,
        title: Optional[str] = None,
        agent: Optional[str] = None,
        model_id: Optional[str] = None,
        provider_id: Optional[str] = None
    ) -> Optional[SessionInfo]:
        """Update a session.

        Args:
            session_id: Session ID
            title: New title
            agent: New agent
            model_id: New model ID
            provider_id: New provider ID

        Returns:
            Updated session or None
        """
        session = cls._sessions.get(session_id)
        if not session:
            return None

        if title is not None:
            session.title = title
        if agent is not None:
            session.agent = agent
        if model_id is not None:
            session.model_id = model_id
        if provider_id is not None:
            session.provider_id = provider_id

        session.time.updated = int(time.time() * 1000)

        log.info("updated session", {"session_id": session_id})

        await Bus.publish(SessionUpdated, SessionUpdatedProperties(session=session))

        return session

    @classmethod
    async def delete(cls, session_id: str) -> bool:
        """Delete a session.

        Args:
            session_id: Session ID

        Returns:
            True if deleted
        """
        if session_id not in cls._sessions:
            return False

        del cls._sessions[session_id]
        if session_id in cls._messages:
            del cls._messages[session_id]

        log.info("deleted session", {"session_id": session_id})

        await Bus.publish(SessionDeleted, SessionDeletedProperties(session_id=session_id))

        return True

    @classmethod
    async def add_message(cls, session_id: str, message: MessageInfo) -> None:
        """Add a message to a session.

        Args:
            session_id: Session ID
            message: Message to add
        """
        if session_id not in cls._messages:
            cls._messages[session_id] = []

        cls._messages[session_id].append(message)

        # Update session timestamp
        session = cls._sessions.get(session_id)
        if session:
            session.time.updated = int(time.time() * 1000)

    @classmethod
    async def get_messages(cls, session_id: str) -> List[MessageInfo]:
        """Get messages for a session.

        Args:
            session_id: Session ID

        Returns:
            List of messages
        """
        return cls._messages.get(session_id, [])

    @classmethod
    async def fork(
        cls,
        session_id: str,
        from_message_id: Optional[str] = None
    ) -> Optional[SessionInfo]:
        """Fork a session from a specific point.

        Args:
            session_id: Session ID to fork
            from_message_id: Message ID to fork from (None = full copy)

        Returns:
            New forked session or None
        """
        session = cls._sessions.get(session_id)
        if not session:
            return None

        messages = cls._messages.get(session_id, [])

        # Create new session
        new_session = await cls.create(
            project_id=session.project_id,
            agent=session.agent,
            directory=session.directory,
            model_id=session.model_id,
            provider_id=session.provider_id,
            parent_id=session_id
        )

        # Copy messages up to the fork point
        new_messages = []
        for msg in messages:
            new_messages.append(msg)
            if from_message_id and msg.id == from_message_id:
                break

        cls._messages[new_session.id] = new_messages

        log.info("forked session", {
            "from": session_id,
            "to": new_session.id,
            "message_count": len(new_messages)
        })

        return new_session

    @classmethod
    def reset(cls) -> None:
        """Reset all sessions (for testing)."""
        cls._sessions.clear()
        cls._messages.clear()
