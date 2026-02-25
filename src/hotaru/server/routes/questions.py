"""Question transport routes."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends

from ...app_services import QuestionService
from ...runtime import AppContext
from ..deps import resolve_app_context
from ..schemas import QuestionReplyRequest

router = APIRouter(prefix="/v1/questions", tags=["questions"])


@router.get("")
async def list_questions(ctx: AppContext = Depends(resolve_app_context)) -> list[dict[str, object]]:
    return await QuestionService.list(ctx)


@router.post("/{request_id}/reply")
async def reply_question(
    request_id: str,
    payload: QuestionReplyRequest = Body(...),
    ctx: AppContext = Depends(resolve_app_context),
) -> bool:
    return await QuestionService.reply(ctx, request_id, payload.model_dump(exclude_none=True))


@router.post("/{request_id}/reject")
async def reject_question(
    request_id: str,
    ctx: AppContext = Depends(resolve_app_context),
) -> bool:
    return await QuestionService.reject(ctx, request_id)
