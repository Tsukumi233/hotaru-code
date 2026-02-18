"""Question application service."""

from __future__ import annotations

from typing import Any

from ..question import Question


class QuestionService:
    """Thin orchestration for question workflows."""

    @classmethod
    async def list(cls) -> list[dict[str, Any]]:
        pending = await Question.list_pending()
        return [item.model_dump() for item in pending]

    @classmethod
    async def reply(cls, request_id: str, payload: dict[str, Any]) -> bool:
        answers = payload.get("answers")
        if not isinstance(answers, list) or any(not isinstance(item, list) for item in answers):
            raise ValueError("Field 'answers' must be a list of string lists")
        if any(any(not isinstance(choice, str) for choice in item) for item in answers):
            raise ValueError("Field 'answers' must contain only strings")

        await Question.reply(request_id, answers)
        return True

    @classmethod
    async def reject(cls, request_id: str) -> bool:
        await Question.reject(request_id)
        return True
