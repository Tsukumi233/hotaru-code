"""Question request/response workflow for interactive tool prompts."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ..core.bus import Bus, BusEvent
from ..core.id import Identifier
from ..util.log import Log

log = Log.create({"service": "question"})


class QuestionOption(BaseModel):
    """A selectable option for a question."""

    label: str = Field(..., description="Display text (1-5 words, concise)")
    description: str = Field(..., description="Explanation of the choice")


class QuestionInfo(BaseModel):
    """Single question payload shown to the user."""

    question: str = Field(..., description="Complete question text")
    header: str = Field(..., description="Short UI label")
    options: List[QuestionOption] = Field(default_factory=list, description="Available choices")
    multiple: Optional[bool] = Field(False, description="Allow selecting multiple choices")
    custom: Optional[bool] = Field(True, description="Allow free-form custom answer")


class QuestionToolRef(BaseModel):
    """Tool call metadata for UI correlation."""

    message_id: str
    call_id: str


class QuestionRequest(BaseModel):
    """Question request published on the event bus."""

    id: str
    session_id: str
    questions: List[QuestionInfo]
    tool: Optional[QuestionToolRef] = None


class QuestionRepliedProperties(BaseModel):
    """Question answer event payload."""

    session_id: str
    request_id: str
    answers: List[List[str]]


class QuestionRejectedProperties(BaseModel):
    """Question rejection event payload."""

    session_id: str
    request_id: str


QuestionAsked = BusEvent.define("question.asked", QuestionRequest)
QuestionReplied = BusEvent.define("question.replied", QuestionRepliedProperties)
QuestionRejected = BusEvent.define("question.rejected", QuestionRejectedProperties)


class RejectedError(Exception):
    """Raised when user dismisses a question request."""

    def __init__(self) -> None:
        super().__init__("The user dismissed this question.")


class Question:
    """Runtime question coordinator."""

    _pending: Dict[str, Dict[str, Any]] = {}

    @classmethod
    async def ask(
        cls,
        *,
        session_id: str,
        questions: List[QuestionInfo],
        tool: Optional[QuestionToolRef] = None,
    ) -> List[List[str]]:
        request_id = Identifier.ascending("question")
        request = QuestionRequest(
            id=request_id,
            session_id=session_id,
            questions=questions,
            tool=tool,
        )
        loop = asyncio.get_event_loop()
        future: asyncio.Future[List[List[str]]] = loop.create_future()
        cls._pending[request_id] = {
            "request": request,
            "resolve": lambda value, f=future: f.set_result(value) if not f.done() else None,
            "reject": lambda e, f=future: f.set_exception(e) if not f.done() else None,
        }
        await Bus.publish(QuestionAsked, request)
        return await future

    @classmethod
    async def reply(cls, request_id: str, answers: List[List[str]]) -> None:
        pending = cls._pending.pop(request_id, None)
        if not pending:
            return

        request: QuestionRequest = pending["request"]
        await Bus.publish(
            QuestionReplied,
            QuestionRepliedProperties(
                session_id=request.session_id,
                request_id=request_id,
                answers=answers,
            ),
        )
        pending["resolve"](answers)

    @classmethod
    async def reject(cls, request_id: str) -> None:
        pending = cls._pending.pop(request_id, None)
        if not pending:
            return

        request: QuestionRequest = pending["request"]
        await Bus.publish(
            QuestionRejected,
            QuestionRejectedProperties(
                session_id=request.session_id,
                request_id=request_id,
            ),
        )
        pending["reject"](RejectedError())

    @classmethod
    async def list_pending(cls) -> List[QuestionRequest]:
        return [pending["request"] for pending in cls._pending.values()]

    @classmethod
    def reset(cls) -> None:
        cls._pending.clear()

