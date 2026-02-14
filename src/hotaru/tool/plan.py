"""Plan mode enter/exit tools."""

from __future__ import annotations

from pydantic import BaseModel

from ..question import Question, QuestionInfo, QuestionOption, RejectedError as QuestionRejectedError
from ..session.session import Session
from .tool import Tool, ToolContext, ToolResult


class PlanParams(BaseModel):
    """No-argument schema."""

    pass


async def plan_enter_execute(_params: PlanParams, ctx: ToolContext) -> ToolResult:
    answers = await Question.ask(
        session_id=ctx.session_id,
        questions=[
            QuestionInfo(
                question="Switch to plan mode and continue with the plan agent?",
                header="Plan Mode",
                custom=False,
                options=[
                    QuestionOption(
                        label="Yes",
                        description="Switch to plan agent for research and planning.",
                    ),
                    QuestionOption(
                        label="No",
                        description="Stay in build mode.",
                    ),
                ],
            )
        ],
    )
    if not answers or not answers[0] or answers[0][0] == "No":
        raise QuestionRejectedError()

    await Session.update(ctx.session_id, agent="plan")
    return ToolResult(
        title="Switched to plan agent",
        output="Plan mode is now active for this session.",
        metadata={},
    )


async def plan_exit_execute(_params: PlanParams, ctx: ToolContext) -> ToolResult:
    answers = await Question.ask(
        session_id=ctx.session_id,
        questions=[
            QuestionInfo(
                question="Plan is complete. Switch back to build agent to implement?",
                header="Build Agent",
                custom=False,
                options=[
                    QuestionOption(
                        label="Yes",
                        description="Switch to build agent and start implementation.",
                    ),
                    QuestionOption(
                        label="No",
                        description="Stay in plan mode and continue refinement.",
                    ),
                ],
            )
        ],
    )
    if not answers or not answers[0] or answers[0][0] == "No":
        raise QuestionRejectedError()

    await Session.update(ctx.session_id, agent="build")
    return ToolResult(
        title="Switched to build agent",
        output="Build mode is now active for this session.",
        metadata={},
    )


PlanEnterTool = Tool.define(
    tool_id="plan_enter",
    description="Switch to plan agent after user confirmation.",
    parameters_type=PlanParams,
    execute_fn=plan_enter_execute,
    auto_truncate=False,
)

PlanExitTool = Tool.define(
    tool_id="plan_exit",
    description="Switch to build agent after user confirmation.",
    parameters_type=PlanParams,
    execute_fn=plan_exit_execute,
    auto_truncate=False,
)
