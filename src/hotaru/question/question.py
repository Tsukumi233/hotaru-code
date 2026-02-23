"""Question request/response workflow for interactive tool prompts."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
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

    @dataclass
    class _Pending:
        request: QuestionRequest
        future: asyncio.Future[List[List[str]]]

    def __init__(self) -> None:
        self._pending: Dict[str, Question._Pending] = {}
        self._guard = asyncio.Lock()

    async def ask(
        self,
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
        loop = asyncio.get_running_loop()
        future: asyncio.Future[List[List[str]]] = loop.create_future()
        async with self._guard:
            self._pending[request_id] = Question._Pending(request=request, future=future)
        await Bus.publish(QuestionAsked, request)
        return await future

    async def reply(self, request_id: str, answers: List[List[str]]) -> None:
        async with self._guard:
            pending = self._pending.pop(request_id, None)
        if not pending:
            return

        request = pending.request
        await Bus.publish(
            QuestionReplied,
            QuestionRepliedProperties(
                session_id=request.session_id,
                request_id=request_id,
                answers=answers,
            ),
        )
        if not pending.future.done():
            pending.future.set_result(answers)

    async def reject(self, request_id: str) -> None:
        async with self._guard:
            pending = self._pending.pop(request_id, None)
        if not pending:
            return

        request = pending.request
        await Bus.publish(
            QuestionRejected,
            QuestionRejectedProperties(
                session_id=request.session_id,
                request_id=request_id,
            ),
        )
        if not pending.future.done():
            pending.future.set_exception(RejectedError())

    async def list_pending(self) -> List[QuestionRequest]:
        async with self._guard:
            return [pending.request for pending in self._pending.values()]

    async def clear_session(self, session_id: str) -> None:
        async with self._guard:
            request_ids = [
                rid
                for rid, pending in self._pending.items()
                if pending.request.session_id == session_id
            ]
            pending = [self._pending.pop(rid) for rid in request_ids]
        for item in pending:
            if not item.future.done():
                item.future.set_exception(RejectedError())

    async def shutdown(self) -> None:
        async with self._guard:
            pending = list(self._pending.values())
            self._pending.clear()
        for item in pending:
            if not item.future.done():
                item.future.set_exception(RejectedError())
