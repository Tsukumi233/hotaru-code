"""Session compaction helpers (incremental port from OpenCode)."""

from __future__ import annotations

import time
from typing import Optional

from ..agent import Agent
from ..core.config import ConfigManager
from ..core.id import Identifier
from ..provider.provider import ProcessedModelInfo
from ..util.log import Log
from .message_store import MessageInfo, MessageTime, ModelRef, TokenUsage
from .message_store import CompactionPart, ToolPart
from .session import Session

log = Log.create({"service": "session.compaction"})


class SessionCompaction:
    COMPACTION_BUFFER = 20_000
    PRUNE_MINIMUM = 20_000
    PRUNE_PROTECT = 40_000
    PRUNE_PROTECTED_TOOLS = {"skill"}

    @classmethod
    async def is_overflow(cls, *, tokens: TokenUsage, model: ProcessedModelInfo) -> bool:
        cfg = await ConfigManager.get()
        if cfg.compaction and cfg.compaction.auto is False:
            return False
        if model.limit.context <= 0:
            return False

        count = (
            tokens.total
            or tokens.input
            + tokens.output
            + tokens.reasoning
            + tokens.cache_read
            + tokens.cache_write
        )
        reserved = min(cls.COMPACTION_BUFFER, model.limit.output)
        usable = (model.limit.input - reserved) if model.limit.input else (model.limit.context - model.limit.output)
        return count >= max(usable, 1)

    @classmethod
    async def create(
        cls,
        *,
        session_id: str,
        agent: str,
        provider_id: str,
        model_id: str,
        auto: bool,
        message_id: Optional[str] = None,
    ) -> str:
        """Create a compaction request as a user message with compaction part."""
        now = int(time.time() * 1000)
        msg_id = message_id or Identifier.ascending("message")
        user = MessageInfo(
            id=msg_id,
            session_id=session_id,
            role="user",
            agent=agent,
            model=ModelRef(provider_id=provider_id, model_id=model_id),
            time=MessageTime(created=now, completed=now),
        )
        await Session.update_message(user)
        await Session.update_part(
            CompactionPart(
                id=Identifier.ascending("part"),
                message_id=msg_id,
                session_id=session_id,
                auto=auto,
            )
        )
        return msg_id

    @classmethod
    async def prune(cls, *, session_id: str) -> None:
        """Mark stale historical tool outputs as compacted.

        This keeps behavior close to OpenCode while remaining conservative:
        only very old tool outputs are compacted, and recent context is kept.
        """
        cfg = await ConfigManager.get()
        if cfg.compaction and cfg.compaction.prune is False:
            return

        msgs = await Session.messages(session_id=session_id)
        total = 0
        pruned = 0
        candidates: list[ToolPart] = []
        turns = 0

        for msg in reversed(msgs):
            if msg.info.role == "user":
                turns += 1
            if turns < 2:
                continue
            if msg.info.role == "assistant" and msg.info.summary:
                break
            for part in reversed(msg.parts):
                if not isinstance(part, ToolPart):
                    continue
                if part.state.status != "completed":
                    continue
                if part.tool in cls.PRUNE_PROTECTED_TOOLS:
                    continue
                if part.state.time.compacted:
                    break

                estimate = len((part.state.output or "").encode("utf-8"))
                total += estimate
                if total > cls.PRUNE_PROTECT:
                    pruned += estimate
                    candidates.append(part)

        if pruned <= cls.PRUNE_MINIMUM:
            return

        now = int(time.time() * 1000)
        for part in candidates:
            part.state.time.compacted = now
            await Session.update_part(part)
        log.info("pruned tool outputs", {"count": len(candidates), "bytes": pruned})

    @classmethod
    async def compact_agent_name(cls) -> str:
        agent = await Agent.get("compaction")
        return agent.name if agent else "compaction"
