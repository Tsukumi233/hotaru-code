"""Question transport routes."""

from __future__ import annotations

from fastapi import APIRouter, Body

from ...app_services import QuestionService
from ..schemas import QuestionReplyRequest

router = APIRouter(prefix="/v1/questions", tags=["questions"])


@router.get("", response_model=list[dict[str, object]])
async def list_questions() -> list[dict[str, object]]:
    result = await QuestionService.list()
    return [dict(item) for item in result]


@router.post("/{request_id}/reply", response_model=bool)
async def reply_question(request_id: str, payload: QuestionReplyRequest = Body(...)) -> bool:
    return await QuestionService.reply(request_id, payload.model_dump(exclude_none=True))


@router.post("/{request_id}/reject", response_model=bool)
async def reject_question(request_id: str) -> bool:
    return await QuestionService.reject(request_id)
