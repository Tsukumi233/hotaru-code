"""Question transport routes."""

from __future__ import annotations

from fastapi import Body, Depends

from ...app_services import QuestionService
from ...runtime import AppContext
from ..deps import resolve_app_context
from ..schemas import QuestionReplyRequest
from .crud import crud_router, raw


async def list_questions(ctx: AppContext = Depends(resolve_app_context)) -> list[dict[str, object]]:
    return await QuestionService.list(ctx)


async def reply_question(
    request_id: str,
    payload: QuestionReplyRequest = Body(...),
    ctx: AppContext = Depends(resolve_app_context),
) -> bool:
    return await QuestionService.reply(ctx, request_id, payload.model_dump(exclude_none=True))


async def reject_question(
    request_id: str,
    ctx: AppContext = Depends(resolve_app_context),
) -> bool:
    return await QuestionService.reject(ctx, request_id)


router = crud_router(
    prefix="/v1/questions",
    tags=["questions"],
    routes=[
        raw("GET", "", list[dict[str, object]], list_questions),
        raw("POST", "/{request_id}/reply", bool, reply_question),
        raw("POST", "/{request_id}/reject", bool, reject_question),
    ],
)
