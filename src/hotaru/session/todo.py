"""Session-scoped todo persistence."""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field

from ..core.bus import Bus, BusEvent
from ..storage import Storage


class TodoInfo(BaseModel):
    """Single todo item."""

    content: str = Field(..., description="Brief description of the task")
    status: str = Field(..., description="Task status: pending, in_progress, completed, cancelled")
    priority: str = Field(..., description="Task priority: high, medium, low")
    id: str = Field(..., description="Unique todo identifier")


class TodoUpdatedProperties(BaseModel):
    """Todo update event payload."""

    session_id: str
    todos: List[TodoInfo]


TodoUpdated = BusEvent.define("todo.updated", TodoUpdatedProperties)


class Todo:
    """Todo storage helper."""

    @classmethod
    async def update(cls, *, session_id: str, todos: List[TodoInfo]) -> None:
        await Storage.write(["todo", session_id], [item.model_dump() for item in todos])
        await Bus.publish(TodoUpdated, TodoUpdatedProperties(session_id=session_id, todos=todos))

    @classmethod
    async def get(cls, session_id: str) -> List[TodoInfo]:
        try:
            rows = await Storage.read(["todo", session_id])
        except Exception:
            return []
        if not isinstance(rows, list):
            return []
        out: List[TodoInfo] = []
        for item in rows:
            try:
                out.append(TodoInfo.model_validate(item))
            except Exception:
                continue
        return out

