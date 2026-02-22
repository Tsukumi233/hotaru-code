"""Question transport routes."""

from __future__ import annotations

from fastapi import Body

from ...app_services import QuestionService
from ..schemas import QuestionReplyRequest
from .crud import crud_router, raw

async def list_questions() -> list[dict[str, object]]:
    return await QuestionService.list()


async def reply_question(request_id: str, payload: QuestionReplyRequest = Body(...)) -> bool:
    return await QuestionService.reply(request_id, payload.model_dump(exclude_none=True))


async def reject_question(request_id: str) -> bool:
    return await QuestionService.reject(request_id)


router = crud_router(
    prefix="/v1/questions",
    tags=["questions"],
    routes=[
        raw("GET", "", list[dict[str, object]], list_questions),
        raw("POST", "/{request_id}/reply", bool, reply_question),
        raw("POST", "/{request_id}/reject", bool, reject_question),
    ],
)
