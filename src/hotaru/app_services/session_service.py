"""Session application service."""

from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncIterator

from ..agent import Agent
from ..core.id import Identifier
from ..provider import Provider
from ..session import Session, SessionCompaction, SessionPrompt


def _session_to_dict(session: Any) -> dict[str, Any]:
    return {
        "id": session.id,
        "project_id": session.project_id,
        "agent": session.agent,
        "model_id": session.model_id,
        "provider_id": session.provider_id,
        "directory": session.directory,
        "parent_id": session.parent_id,
        "time": {
            "created": session.time.created,
            "updated": session.time.updated,
        },
    }


class SessionService:
    """Thin orchestration for session workflows."""

    @classmethod
    async def _resolve_model(
        cls,
        payload: dict[str, Any],
        *,
        fallback_provider_id: str | None = None,
        fallback_model_id: str | None = None,
    ) -> tuple[str, str]:
        model = payload.get("model")
        if isinstance(model, str) and model.strip():
            provider_id, model_id = Provider.parse_model(model)
            return provider_id, model_id

        provider_id = (
            payload.get("provider_id")
            or payload.get("providerID")
            or fallback_provider_id
        )
        model_id = payload.get("model_id") or payload.get("modelID") or fallback_model_id

        if provider_id and model_id:
            return str(provider_id), str(model_id)

        return await Provider.default_model()

    @classmethod
    async def create(cls, payload: dict[str, Any], cwd: str) -> dict[str, Any]:
        project_id = payload.get("project_id") or payload.get("projectID") or "default"
        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("Field 'project_id' must be a non-empty string")

        provider_id, model_id = await cls._resolve_model(payload)
        agent_name = payload.get("agent") or await Agent.default_agent()
        if not isinstance(agent_name, str) or not agent_name.strip():
            raise ValueError("Field 'agent' must be a non-empty string")

        directory = payload.get("directory") or cwd
        parent_id = payload.get("parent_id") or payload.get("parentID")

        session = await Session.create(
            project_id=project_id.strip(),
            agent=agent_name.strip(),
            directory=str(directory),
            model_id=str(model_id),
            provider_id=str(provider_id),
            parent_id=str(parent_id) if isinstance(parent_id, str) and parent_id else None,
        )
        return _session_to_dict(session)

    @classmethod
    async def list(cls, project_id: str) -> list[dict[str, Any]]:
        if not project_id:
            raise ValueError("Query parameter 'project_id' is required")
        sessions = await Session.list(project_id)
        return [_session_to_dict(session) for session in sessions]

    @classmethod
    async def get(cls, session_id: str) -> dict[str, Any] | None:
        session = await Session.get(session_id)
        if not session:
            return None
        return _session_to_dict(session)

    @classmethod
    async def compact(cls, session_id: str, payload: dict[str, Any], cwd: str) -> dict[str, Any]:
        session = await Session.get(session_id)
        if not session:
            raise KeyError(f"Session '{session_id}' not found")

        provider_id, model_id = await cls._resolve_model(
            payload,
            fallback_provider_id=session.provider_id,
            fallback_model_id=session.model_id,
        )

        try:
            await Provider.get_model(provider_id, model_id)
        except Exception as exc:
            raise ValueError(str(exc)) from exc

        auto = bool(payload.get("auto", False))
        agent_name = session.agent or await Agent.default_agent()
        worktree = session.directory or cwd

        await SessionCompaction.create(
            session_id=session_id,
            agent=agent_name,
            provider_id=provider_id,
            model_id=model_id,
            auto=auto,
        )

        result = await SessionPrompt.loop(
            session_id=session_id,
            provider_id=provider_id,
            model_id=model_id,
            agent=agent_name,
            cwd=worktree,
            worktree=worktree,
            resume_history=True,
            auto_compaction=False,
        )

        return {
            "ok": result.result.error is None,
            "assistant_message_id": result.assistant_message_id,
            "status": result.result.status,
            "error": result.result.error,
        }

    @classmethod
    async def stream_message(
        cls,
        session_id: str,
        payload: dict[str, Any],
        cwd: str,
    ) -> AsyncIterator[dict[str, Any]]:
        content = payload.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Field 'content' must be a non-empty string")

        session = await Session.get(session_id)
        if not session:
            raise KeyError(f"Session '{session_id}' not found")

        provider_id, model_id = await cls._resolve_model(
            payload,
            fallback_provider_id=session.provider_id,
            fallback_model_id=session.model_id,
        )

        agent_name = payload.get("agent") or session.agent or await Agent.default_agent()
        if not isinstance(agent_name, str) or not agent_name.strip():
            raise ValueError("Field 'agent' must be a non-empty string")

        worktree = session.directory or cwd
        assistant_message_id = Identifier.ascending("message")

        yield {
            "type": "message.created",
            "data": {
                "id": assistant_message_id,
                "role": "assistant",
            },
        }

        try:
            result = await SessionPrompt.prompt(
                session_id=session_id,
                content=content,
                provider_id=str(provider_id),
                model_id=str(model_id),
                agent=agent_name.strip(),
                cwd=str(Path(worktree)),
                worktree=str(Path(worktree)),
                resume_history=True,
                assistant_message_id=assistant_message_id,
            )
        except Exception as exc:
            yield {
                "type": "error",
                "data": {"error": str(exc)},
            }
            return

        if result.result.error:
            yield {
                "type": "error",
                "data": {"error": str(result.result.error)},
            }
            return

        yield {
            "type": "message.completed",
            "data": {
                "id": result.assistant_message_id,
                "finish": result.result.stop_reason or "stop",
                "usage": dict(result.result.usage or {}),
            },
        }
