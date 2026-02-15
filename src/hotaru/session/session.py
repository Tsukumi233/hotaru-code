"""Session management.

Sessions track conversations between users and AI agents.
Persisted via the hierarchical JSON file storage layer.
"""

import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ..core.bus import Bus, BusEvent
from ..core.id import Identifier
from ..core.global_paths import GlobalPath
from ..storage import Storage, NotFoundError
from ..util.log import Log
from .message_store import MessageInfo as StoredMessageInfo
from .message_store import Part as StoredMessagePart
from .message_store import WithParts as StoredMessageWithParts
from .message_store import parse_part

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
    slug: Optional[str] = None
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
    def _message_store_key(session_id: str, message_id: str) -> List[str]:
        return ["message_store", session_id, message_id]

    @staticmethod
    def _part_key(session_id: str, part_id: str) -> List[str]:
        return ["part", session_id, part_id]

    @classmethod
    async def _touch_session(cls, session_id: str) -> None:
        """Update session.updated timestamp."""
        session = await cls.get(session_id)
        if not session:
            return
        try:
            await Storage.update(
                cls._session_key(session.project_id, session_id),
                lambda d: d["time"].__setitem__("updated", int(time.time() * 1000)),
            )
        except NotFoundError:
            return

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
            slug=session_id,
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
    def plan_path_for(
        cls,
        session: SessionInfo,
        *,
        worktree: Optional[str] = None,
        is_git: Optional[bool] = None,
    ) -> str:
        """Return the canonical plan file path for a session."""
        if is_git is None:
            is_git = bool(worktree and worktree != "/")

        if is_git and worktree:
            base = Path(worktree) / ".hotaru" / "plans"
        else:
            base = Path(GlobalPath.data()) / "plans"

        slug = session.slug or session.id
        filename = f"{session.time.created}-{slug}.md"
        return str(base / filename)

    @classmethod
    async def plan_path(
        cls,
        session_id: str,
        *,
        worktree: Optional[str] = None,
        is_git: Optional[bool] = None,
    ) -> Optional[str]:
        """Resolve the canonical plan file path for a session id."""
        session = await cls.get(session_id)
        if not session:
            return None
        return cls.plan_path_for(session, worktree=worktree, is_git=is_git)

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
        stored_msg_keys = await Storage.list(["message_store", session_id])
        for key in stored_msg_keys:
            await Storage.remove(key)
        part_keys = await Storage.list(["part", session_id])
        for key in part_keys:
            await Storage.remove(key)

        # Delete the session itself
        await Storage.remove(cls._session_key(session.project_id, session_id))

        log.info("deleted session", {"session_id": session_id})
        await Bus.publish(SessionDeleted, SessionDeletedProperties(session_id=session_id))
        return True

    @classmethod
    async def update_message(cls, message: StoredMessageInfo) -> StoredMessageInfo:
        """Upsert a structured message info record."""
        await Storage.write(
            cls._message_store_key(message.session_id, message.id),
            message.model_dump(),
        )
        await cls._touch_session(message.session_id)
        return message

    @classmethod
    async def get_message(cls, session_id: str, message_id: str) -> Optional[StoredMessageInfo]:
        """Get one structured message info record by id."""
        try:
            data = await Storage.read(cls._message_store_key(session_id, message_id))
        except NotFoundError:
            return None
        try:
            return StoredMessageInfo.model_validate(data)
        except Exception:
            return None

    @classmethod
    async def update_part(cls, part: StoredMessagePart) -> StoredMessagePart:
        """Upsert a structured message part record."""
        await Storage.write(
            cls._part_key(part.session_id, part.id),
            part.model_dump(),
        )
        await cls._touch_session(part.session_id)
        return part

    @classmethod
    async def update_part_delta(
        cls,
        *,
        session_id: str,
        message_id: str,
        part_id: str,
        field: str,
        delta: str,
    ) -> Optional[StoredMessagePart]:
        """Append string delta to a part field (e.g. text/reasoning)."""
        key = cls._part_key(session_id, part_id)
        try:
            raw = await Storage.update(
                key,
                lambda d: d.__setitem__(field, str(d.get(field, "")) + delta),
            )
        except NotFoundError:
            return None
        part = parse_part(raw)
        if getattr(part, "message_id", None) != message_id:
            return None
        await cls._touch_session(session_id)
        return part

    @classmethod
    async def parts(cls, session_id: str, message_id: str) -> List[StoredMessagePart]:
        """List structured message parts for a message, ordered by part id."""
        keys = await Storage.list(["part", session_id])
        result: List[StoredMessagePart] = []
        for key in keys:
            try:
                data = await Storage.read(key)
                part = parse_part(data)
            except Exception:
                continue
            if part.message_id == message_id:
                result.append(part)
        result.sort(key=lambda p: p.id)
        return result

    @classmethod
    async def messages(cls, *, session_id: str) -> List[StoredMessageWithParts]:
        """List structured messages with all their parts."""
        message_keys = await Storage.list(["message_store", session_id])
        infos: List[StoredMessageInfo] = []
        for key in message_keys:
            try:
                data = await Storage.read(key)
                info = StoredMessageInfo.model_validate(data)
            except Exception:
                continue
            infos.append(info)
        infos.sort(key=lambda i: i.id)

        part_keys = await Storage.list(["part", session_id])
        by_message: Dict[str, List[StoredMessagePart]] = {}
        for key in part_keys:
            try:
                data = await Storage.read(key)
                part = parse_part(data)
            except Exception:
                continue
            by_message.setdefault(part.message_id, []).append(part)
        for parts in by_message.values():
            parts.sort(key=lambda p: p.id)

        return [StoredMessageWithParts(info=info, parts=by_message.get(info.id, [])) for info in infos]

    @classmethod
    async def delete_messages(
        cls,
        session_id: str,
        message_ids: List[str],
    ) -> int:
        """Delete specific messages from a session.

        Args:
            session_id: Session ID
            message_ids: Message IDs to remove

        Returns:
            Number of requested message IDs processed
        """
        if not message_ids:
            return 0

        session = await cls.get(session_id)
        if not session:
            return 0

        for message_id in message_ids:
            await Storage.remove(cls._message_store_key(session_id, message_id))
        part_keys = await Storage.list(["part", session_id])
        for key in part_keys:
            try:
                part_data = await Storage.read(key)
            except NotFoundError:
                continue
            if part_data.get("message_id") in message_ids:
                await Storage.remove(key)

        try:
            updated_data = await Storage.update(
                cls._session_key(session.project_id, session_id),
                lambda d: d["time"].__setitem__("updated", int(time.time() * 1000)),
            )
        except NotFoundError:
            return 0
        updated_session = SessionInfo.model_validate(updated_data)
        await Bus.publish(SessionUpdated, SessionUpdatedProperties(session=updated_session))

        return len(message_ids)

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

        messages = await cls.messages(session_id=session_id)

        # Create new session
        new_session = await cls.create(
            project_id=session.project_id,
            agent=session.agent,
            directory=session.directory,
            model_id=session.model_id,
            provider_id=session.provider_id,
            parent_id=session_id
        )

        # Deep-copy structured messages + parts up to the fork point.
        id_map: Dict[str, str] = {}
        for msg in messages:
            old_id = msg.info.id
            new_id = Identifier.ascending("message")
            id_map[old_id] = new_id

            cloned_info = msg.info.model_copy(deep=True)
            cloned_info.id = new_id
            cloned_info.session_id = new_session.id
            if cloned_info.parent_id:
                cloned_info.parent_id = id_map.get(cloned_info.parent_id)
            await cls.update_message(cloned_info)

            for part in msg.parts:
                cloned_part = part.model_copy(deep=True)
                cloned_part.id = Identifier.ascending("part")
                cloned_part.session_id = new_session.id
                cloned_part.message_id = new_id
                await cls.update_part(cloned_part)

            if from_message_id and old_id == from_message_id:
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
