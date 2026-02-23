"""Question tool for collecting structured user input."""

from __future__ import annotations

from pathlib import Path
from typing import List

from pydantic import BaseModel, Field

from ..question import QuestionInfo, QuestionToolRef
from .tool import Tool, ToolContext, ToolResult

DESCRIPTION = (Path(__file__).parent / "question.txt").read_text(encoding="utf-8")


class QuestionParams(BaseModel):
    """Parameters for question tool."""

    questions: List[QuestionInfo] = Field(..., description="Questions to ask")


async def question_execute(params: QuestionParams, ctx: ToolContext) -> ToolResult:
    answers = await ctx.app.question.ask(
        session_id=ctx.session_id,
        questions=params.questions,
        tool=QuestionToolRef(message_id=ctx.message_id, call_id=ctx.call_id or ""),
    )

    def _fmt(answer: List[str]) -> str:
        if not answer:
            return "Unanswered"
        return ", ".join(answer)

    formatted = ", ".join(
        f"\"{question.question}\"=\"{_fmt(answers[idx] if idx < len(answers) else [])}\""
        for idx, question in enumerate(params.questions)
    )

    return ToolResult(
        title=f"Asked {len(params.questions)} question{'s' if len(params.questions) != 1 else ''}",
        output=f"User has answered your questions: {formatted}. Continue with these answers in mind.",
        metadata={"answers": answers},
    )


QuestionTool = Tool.define(
    tool_id="question",
    description=DESCRIPTION,
    parameters_type=QuestionParams,
    execute_fn=question_execute,
    auto_truncate=False,
)
