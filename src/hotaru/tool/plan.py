"""Plan mode enter/exit tools."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from ..question import (
    Question,
    QuestionInfo,
    QuestionOption,
    QuestionToolRef,
    RejectedError as QuestionRejectedError,
)
from ..session.session import Session
from .tool import Tool, ToolContext, ToolResult


class PlanParams(BaseModel):
    """No-argument schema."""

    pass


async def plan_enter_execute(_params: PlanParams, ctx: ToolContext) -> ToolResult:
    session = await Session.get(ctx.session_id)
    if not session:
        raise ValueError(f"Session not found: {ctx.session_id}")

    is_git = bool(ctx.extra.get("worktree")) and str(ctx.extra.get("worktree")) != "/"
    plan_path = Session.plan_path_for(
        session,
        worktree=str(ctx.extra.get("worktree") or ""),
        is_git=is_git,
    )
    display = plan_path
    worktree = str(ctx.extra.get("worktree") or "")
    if worktree and worktree != "/":
        try:
            display = str(Path(plan_path).resolve().relative_to(Path(worktree).resolve()))
        except ValueError:
            pass

    answers = await Question.ask(
        session_id=ctx.session_id,
        questions=[
            QuestionInfo(
                question=f"Would you like to switch to the plan agent and create a plan saved to {display}?",
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
        tool=QuestionToolRef(message_id=ctx.message_id, call_id=ctx.call_id)
        if ctx.call_id
        else None,
    )
    if not answers or not answers[0] or answers[0][0] == "No":
        raise QuestionRejectedError()

    await Session.update(ctx.session_id, agent="plan")
    return ToolResult(
        title="Switching to plan agent",
        output=f"User confirmed to switch to plan mode. The plan file will be at {display}. Begin planning.",
        metadata={
            "mode_switch": {
                "from": "build",
                "to": "plan",
                "plan_path": plan_path,
            },
            "synthetic_user": {
                "agent": "plan",
                "text": "User has requested to enter plan mode. Switch to plan mode and begin planning.",
            },
        },
    )


async def plan_exit_execute(_params: PlanParams, ctx: ToolContext) -> ToolResult:
    session = await Session.get(ctx.session_id)
    if not session:
        raise ValueError(f"Session not found: {ctx.session_id}")

    is_git = bool(ctx.extra.get("worktree")) and str(ctx.extra.get("worktree")) != "/"
    plan_path = Session.plan_path_for(
        session,
        worktree=str(ctx.extra.get("worktree") or ""),
        is_git=is_git,
    )
    display = plan_path
    worktree = str(ctx.extra.get("worktree") or "")
    if worktree and worktree != "/":
        try:
            display = str(Path(plan_path).resolve().relative_to(Path(worktree).resolve()))
        except ValueError:
            pass

    answers = await Question.ask(
        session_id=ctx.session_id,
        questions=[
            QuestionInfo(
                question=f"Plan at {display} is complete. Would you like to switch to the build agent and start implementing?",
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
        tool=QuestionToolRef(message_id=ctx.message_id, call_id=ctx.call_id)
        if ctx.call_id
        else None,
    )
    if not answers or not answers[0] or answers[0][0] == "No":
        raise QuestionRejectedError()

    await Session.update(ctx.session_id, agent="build")
    return ToolResult(
        title="Switching to build agent",
        output="User approved switching to build agent. Wait for further instructions.",
        metadata={
            "mode_switch": {
                "from": "plan",
                "to": "build",
                "plan_path": plan_path,
            },
            "synthetic_user": {
                "agent": "build",
                "text": f"The plan at {display} has been approved, you can now edit files. Execute the plan",
            },
        },
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
