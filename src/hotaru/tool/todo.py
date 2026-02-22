"""Todo read/write tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

from pydantic import BaseModel, Field

from ..session.todo import Todo, TodoInfo
from .tool import PermissionSpec, Tool, ToolContext, ToolResult


class TodoWriteParams(BaseModel):
    """Parameters for todowrite."""

    todos: List[TodoInfo] = Field(..., description="Updated todo list")


class TodoReadParams(BaseModel):
    """Parameters for todoread."""

    # Empty object schema
    pass


async def todo_write_execute(params: TodoWriteParams, ctx: ToolContext) -> ToolResult:
    await Todo.update(session_id=ctx.session_id, todos=params.todos)
    remaining = len([todo for todo in params.todos if todo.status != "completed"])
    return ToolResult(
        title=f"{remaining} todos",
        output=json.dumps([todo.model_dump() for todo in params.todos], indent=2),
        metadata={"todos": [todo.model_dump() for todo in params.todos]},
    )


async def todo_read_execute(_params: TodoReadParams, ctx: ToolContext) -> ToolResult:
    todos = await Todo.get(ctx.session_id)
    remaining = len([todo for todo in todos if todo.status != "completed"])
    payload = [todo.model_dump() for todo in todos]
    return ToolResult(
        title=f"{remaining} todos",
        output=json.dumps(payload, indent=2),
        metadata={"todos": payload},
    )


_TODOWRITE_DESC = (Path(__file__).parent / "todowrite.txt").read_text(encoding="utf-8")
_TODOREAD_DESC = (Path(__file__).parent / "todoread.txt").read_text(encoding="utf-8")


def _todo_write_permissions(_params: TodoWriteParams, _ctx: ToolContext) -> list[PermissionSpec]:
    return [PermissionSpec(permission="todowrite", patterns=["*"], always=["*"], metadata={})]


def _todo_read_permissions(_params: TodoReadParams, _ctx: ToolContext) -> list[PermissionSpec]:
    return [PermissionSpec(permission="todoread", patterns=["*"], always=["*"], metadata={})]

TodoWriteTool = Tool.define(
    tool_id="todowrite",
    description=_TODOWRITE_DESC,
    parameters_type=TodoWriteParams,
    permission_fn=_todo_write_permissions,
    execute_fn=todo_write_execute,
    auto_truncate=False,
)

TodoReadTool = Tool.define(
    tool_id="todoread",
    description=_TODOREAD_DESC,
    parameters_type=TodoReadParams,
    permission_fn=_todo_read_permissions,
    execute_fn=todo_read_execute,
    auto_truncate=False,
)
