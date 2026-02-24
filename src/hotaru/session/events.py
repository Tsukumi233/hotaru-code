"""Session event definitions and property models.

All BusEvent instances related to session and message lifecycle
are defined here so they can be imported without pulling in
the full Session class.
"""

from typing import Any, Dict

from pydantic import BaseModel

from ..core.bus import BusEvent


class SessionCreatedProperties(BaseModel):
    """Properties for session created event."""
    session: Any  # SessionInfo — avoids circular import


class SessionUpdatedProperties(BaseModel):
    """Properties for session updated event."""
    session: Any  # SessionInfo


class SessionDeletedProperties(BaseModel):
    """Properties for session deleted event."""
    session_id: str


class MessageUpdatedProperties(BaseModel):
    """Properties for message.updated event."""
    info: Dict[str, Any]


class MessagePartUpdatedProperties(BaseModel):
    """Properties for message.part.updated event."""
    part: Dict[str, Any]


class MessagePartDeltaProperties(BaseModel):
    """Properties for message.part.delta event."""
    session_id: str
    message_id: str
    part_id: str
    field: str
    delta: str


class SessionStatusProperties(BaseModel):
    """Properties for session.status event."""
    session_id: str
    status: Dict[str, Any]


SessionCreated = BusEvent(
    event_type="session.created",
    properties_type=SessionCreatedProperties,
)

SessionUpdated = BusEvent(
    event_type="session.updated",
    properties_type=SessionUpdatedProperties,
)

SessionDeleted = BusEvent(
    event_type="session.deleted",
    properties_type=SessionDeletedProperties,
)

MessageUpdated = BusEvent(
    event_type="message.updated",
    properties_type=MessageUpdatedProperties,
)

MessagePartUpdated = BusEvent(
    event_type="message.part.updated",
    properties_type=MessagePartUpdatedProperties,
)

MessagePartDelta = BusEvent(
    event_type="message.part.delta",
    properties_type=MessagePartDeltaProperties,
)

SessionStatus = BusEvent(
    event_type="session.status",
    properties_type=SessionStatusProperties,
)
