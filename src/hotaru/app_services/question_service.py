"""Question application service."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..runtime import AppContext


class QuestionService:
    """Thin orchestration for question workflows."""

    @classmethod
    async def list(cls, app: AppContext) -> list[dict[str, Any]]:
        pending = await app.question.list_pending()
        return [item.model_dump() for item in pending]

    @classmethod
    async def reply(cls, app: AppContext, request_id: str, payload: dict[str, Any]) -> bool:
        answers = payload.get("answers")
        if not isinstance(answers, list) or any(not isinstance(item, list) for item in answers):
            raise ValueError("Field 'answers' must be a list of string lists")
        if any(any(not isinstance(choice, str) for choice in item) for item in answers):
            raise ValueError("Field 'answers' must contain only strings")

        await app.question.reply(request_id, answers)
        return True

    @classmethod
    async def reject(cls, app: AppContext, request_id: str) -> bool:
        await app.question.reject(request_id)
        return True
