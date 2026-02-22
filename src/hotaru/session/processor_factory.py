"""Factory for assembling SessionProcessor collaborators."""

from __future__ import annotations

from typing import Optional

from .agent_flow import AgentFlow
from .history_loader import HistoryLoader
from .processor import SessionProcessor
from .turn_preparer import TurnPreparer


class SessionProcessorFactory:
    """Build SessionProcessor with default collaborator graph."""

    @staticmethod
    def build(
        *,
        session_id: str,
        model_id: str,
        provider_id: str,
        agent: str,
        cwd: str,
        worktree: Optional[str] = None,
        max_turns: int = 100,
        sync_agent_from_session: bool = True,
    ) -> SessionProcessor:
        # Processor wires DoomLoopDetector + ToolExecutor + TurnRunner by default.
        return SessionProcessor(
            session_id=session_id,
            model_id=model_id,
            provider_id=provider_id,
            agent=agent,
            cwd=cwd,
            worktree=worktree,
            max_turns=max_turns,
            sync_agent_from_session=sync_agent_from_session,
            history=HistoryLoader(),
            agentflow=AgentFlow(),
            turnprep=TurnPreparer(),
            turnrun=None,
            tools=None,
            doom=None,
        )
