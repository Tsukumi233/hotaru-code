"""Session application service."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path
from typing import Any

from ..agent import Agent
from ..core.bus import Bus
from ..project import Project
from ..provider import Provider
from ..session import (
    Session,
    SessionCompaction,
    SessionPrompt,
    SessionStatus,
    SessionStatusProperties,
)
from ..session.message_store import MessageInfo as StoredMessageInfo
from ..session.message_store import parse_part
from .session_payload import structured_messages_to_payload


def _reject_legacy_fields(payload: dict[str, Any], aliases: dict[str, str]) -> None:
    for legacy_name, canonical_name in aliases.items():
        if legacy_name in payload:
            raise ValueError(
                f"Field '{legacy_name}' is not supported. Use '{canonical_name}' instead."
            )


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

    _tasks: dict[str, asyncio.Task[object]] = {}

    @classmethod
    def _register_task(cls, session_id: str, task: asyncio.Task[object]) -> None:
        prev = cls._tasks.get(session_id)
        if prev and not prev.done():
            raise ValueError("Session already has an active request")
        cls._tasks[session_id] = task

    @classmethod
    def _clear_task(cls, session_id: str, task: asyncio.Task[object]) -> None:
        current = cls._tasks.get(session_id)
        if current is task:
            del cls._tasks[session_id]

    @classmethod
    def reset_runtime(cls) -> None:
        for task in list(cls._tasks.values()):
            task.cancel()
        cls._tasks.clear()

    @classmethod
    async def _resolve_model(
        cls,
        payload: dict[str, Any],
        *,
        fallback_provider_id: str | None = None,
        fallback_model_id: str | None = None,
    ) -> tuple[str, str]:
        _reject_legacy_fields(
            payload,
            {
                "providerID": "provider_id",
                "modelID": "model_id",
            },
        )
        model = payload.get("model")
        if isinstance(model, str) and model.strip():
            provider_id, model_id = Provider.parse_model(model)
            return provider_id, model_id

        provider_id = payload.get("provider_id") or fallback_provider_id
        model_id = payload.get("model_id") or fallback_model_id

        if provider_id and model_id:
            return str(provider_id), str(model_id)

        return await Provider.default_model()

    @classmethod
    async def _resolve_project_id(cls, payload: dict[str, Any], cwd: str) -> str:
        project_id = payload.get("project_id")
        if project_id is not None:
            if not isinstance(project_id, str) or not project_id.strip():
                raise ValueError("Field 'project_id' must be a non-empty string")
            return project_id.strip()

        project, _ = await Project.from_directory(cwd)
        return project.id

    @classmethod
    async def create(cls, payload: dict[str, Any], cwd: str) -> dict[str, Any]:
        _reject_legacy_fields(
            payload,
            {
                "projectID": "project_id",
                "parentID": "parent_id",
            },
        )
        directory = str(payload.get("directory") or payload.get("cwd") or cwd)
        project_id = await cls._resolve_project_id(payload, directory)
        provider_id, model_id = await cls._resolve_model(payload)
        agent_name = payload.get("agent") or await Agent.default_agent()
        if not isinstance(agent_name, str) or not agent_name.strip():
            raise ValueError("Field 'agent' must be a non-empty string")

        parent_id = payload.get("parent_id")

        session = await Session.create(
            project_id=project_id.strip(),
            agent=agent_name.strip(),
            directory=directory,
            model_id=str(model_id),
            provider_id=str(provider_id),
            parent_id=str(parent_id) if isinstance(parent_id, str) and parent_id else None,
        )
        return _session_to_dict(session)

    @classmethod
    async def list(cls, project_id: str | None, cwd: str) -> list[dict[str, Any]]:
        resolved_project_id = await cls._resolve_project_id(
            {"project_id": project_id} if project_id is not None else {},
            cwd,
        )
        sessions = await Session.list(resolved_project_id)
        return [_session_to_dict(session) for session in sessions]

    @classmethod
    async def get(cls, session_id: str) -> dict[str, Any] | None:
        session = await Session.get(session_id)
        if not session:
            return None
        return _session_to_dict(session)

    @classmethod
    async def update(cls, session_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        title = payload.get("title")
        if title is not None and not isinstance(title, str):
            raise ValueError("Field 'title' must be a string")

        updated = await Session.update(
            session_id=session_id,
            title=title.strip() if isinstance(title, str) else None,
        )
        if not updated:
            return None
        return _session_to_dict(updated)

    @classmethod
    async def delete(cls, session_id: str) -> dict[str, bool]:
        deleted = await Session.delete(session_id)
        if not deleted:
            raise KeyError(f"Session '{session_id}' not found")
        return {"ok": True}

    @classmethod
    async def list_messages(cls, session_id: str) -> list[dict[str, Any]]:
        session = await Session.get(session_id)
        if not session:
            raise KeyError(f"Session '{session_id}' not found")
        structured = await Session.messages(session_id=session_id)
        return structured_messages_to_payload(structured)

    @classmethod
    async def delete_messages(cls, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        _reject_legacy_fields(payload, {"messageIDs": "message_ids"})
        raw_message_ids = payload.get("message_ids") or []
        if not isinstance(raw_message_ids, list):
            raise ValueError("Field 'message_ids' must be a list of strings")

        message_ids: list[str] = []
        seen: set[str] = set()
        for item in raw_message_ids:
            message_id = str(item or "").strip()
            if not message_id or message_id in seen:
                continue
            seen.add(message_id)
            message_ids.append(message_id)

        deleted = await Session.delete_messages(session_id, message_ids)
        return {"deleted": int(deleted)}

    @classmethod
    async def restore_messages(cls, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        session = await Session.get(session_id)
        if not session:
            raise KeyError(f"Session '{session_id}' not found")

        raw_messages = payload.get("messages")
        if not isinstance(raw_messages, list):
            raise ValueError("Field 'messages' must be a list")

        restored = 0
        for raw_message in raw_messages:
            if not isinstance(raw_message, dict):
                continue

            info_data = raw_message.get("info")
            if not isinstance(info_data, dict):
                continue

            try:
                structured_info = StoredMessageInfo.model_validate(info_data)
            except Exception:
                continue

            if structured_info.session_id != session_id:
                structured_info = structured_info.model_copy(update={"session_id": session_id})
            await Session.update_message(structured_info)

            raw_parts = raw_message.get("parts")
            if isinstance(raw_parts, list):
                for raw_part in raw_parts:
                    if not isinstance(raw_part, dict):
                        continue
                    try:
                        part = parse_part(raw_part)
                    except Exception:
                        continue
                    if part.session_id != session_id or part.message_id != structured_info.id:
                        part = part.model_copy(
                            update={
                                "session_id": session_id,
                                "message_id": structured_info.id,
                            }
                        )
                    await Session.update_part(part)
            restored += 1

        return {"restored": restored}

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
    async def message(
        cls,
        session_id: str,
        payload: dict[str, Any],
        cwd: str,
    ) -> dict[str, Any]:
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
        task = asyncio.create_task(
            SessionPrompt.prompt(
                session_id=session_id,
                content=content,
                provider_id=str(provider_id),
                model_id=str(model_id),
                agent=agent_name.strip(),
                cwd=str(Path(worktree)),
                worktree=str(Path(worktree)),
                resume_history=True,
            )
        )

        try:
            cls._register_task(session_id, task)
        except ValueError:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            raise
        working = False

        try:
            await Bus.publish(
                SessionStatus,
                SessionStatusProperties(session_id=session_id, status={"type": "working"}),
            )
            working = True
            result = await task
            return {
                "ok": result.result.error is None,
                "assistant_message_id": result.assistant_message_id,
                "status": result.result.status,
                "error": result.result.error,
            }
        except asyncio.CancelledError:
            return {
                "ok": False,
                "assistant_message_id": "",
                "status": "interrupted",
                "error": None,
            }
        finally:
            cls._clear_task(session_id, task)
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            if working:
                await Bus.publish(
                    SessionStatus,
                    SessionStatusProperties(session_id=session_id, status={"type": "idle"}),
                )

    @classmethod
    async def interrupt(cls, session_id: str) -> dict[str, Any]:
        session = await Session.get(session_id)
        if not session:
            raise KeyError(f"Session '{session_id}' not found")

        task = cls._tasks.get(session_id)
        if not task or task.done():
            return {"ok": True, "interrupted": False}
        task.cancel()
        return {"ok": True, "interrupted": True}
