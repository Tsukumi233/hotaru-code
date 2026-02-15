"""Session summary helpers."""

from __future__ import annotations

from typing import Dict, List

from ..util.log import Log
from .session import Session

log = Log.create({"service": "session.summary"})


class SessionSummary:
    """Summary utilities.

    This is an incremental port. It currently provides:
    - lightweight title generation from the user prompt
    - placeholder diff stats (to be replaced with snapshot diff integration)
    """

    @classmethod
    async def summarize(cls, *, session_id: str, message_id: str) -> None:
        structured = await Session.messages(session_id=session_id)
        user = next((m for m in structured if m.info.id == message_id and m.info.role == "user"), None)
        if not user:
            return

        text_chunks: List[str] = []
        for part in user.parts:
            if getattr(part, "type", "") == "text":
                text = getattr(part, "text", "")
                if isinstance(text, str) and text.strip():
                    text_chunks.append(text.strip())
        if not text_chunks:
            return

        title = cls._title_from_text(" ".join(text_chunks))
        session = await Session.get(session_id)
        if session and (not session.title):
            await Session.update(session_id, project_id=session.project_id, title=title)

    @staticmethod
    def _title_from_text(text: str) -> str:
        words = [w for w in text.replace("\n", " ").split(" ") if w]
        if not words:
            return "Untitled"
        return " ".join(words[:7]).strip()[:120]

    @classmethod
    async def diff(cls, *, session_id: str) -> List[Dict[str, object]]:
        # Placeholder until snapshot tracking is wired into step parts.
        return []
