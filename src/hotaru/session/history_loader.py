"""History loading for session processor."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..util.log import Log

log = Log.create({"service": "session.history_loader"})


class HistoryLoader:
    """Load and normalize persisted session history."""

    async def load(self, *, session_id: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        from .message_store import filter_compacted, to_model_messages
        from .session import Session

        stored = await Session.messages(session_id=session_id)
        filtered = filter_compacted(stored)
        messages = to_model_messages(filtered)

        last_assistant_agent: Optional[str] = None
        for msg in reversed(filtered):
            if msg.info.role != "assistant":
                continue
            if msg.info.agent:
                last_assistant_agent = msg.info.agent
            break

        log.info(
            "loaded history",
            {
                "session_id": session_id,
                "message_count": len(messages),
                "source": "message_store",
            },
        )
        return messages, last_assistant_agent
