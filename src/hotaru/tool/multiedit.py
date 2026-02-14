"""MultiEdit tool for sequential edits on one file."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from .edit import EditParams, EditTool
from .tool import Tool, ToolContext, ToolResult


class MultiEditOperation(BaseModel):
    """Single edit operation."""

    file_path: Optional[str] = Field(None, alias="filePath", description="Absolute file path")
    old_string: str = Field(..., alias="oldString", description="Text to replace")
    new_string: str = Field(..., alias="newString", description="Replacement text")
    replace_all: Optional[bool] = Field(False, alias="replaceAll", description="Replace all occurrences")

    class Config:
        populate_by_name = True


class MultiEditParams(BaseModel):
    """Parameters for multiedit."""

    file_path: str = Field(..., alias="filePath", description="Absolute file path to modify")
    edits: List[MultiEditOperation] = Field(..., description="Edit operations to run sequentially")

    class Config:
        populate_by_name = True


async def multiedit_execute(params: MultiEditParams, ctx: ToolContext) -> ToolResult:
    results = []
    for edit in params.edits:
        edit_params = EditParams(
            file_path=params.file_path,
            old_string=edit.old_string,
            new_string=edit.new_string,
            replace_all=bool(edit.replace_all),
        )
        result = await EditTool.execute(edit_params, ctx)
        results.append(result)

    final = results[-1] if results else ToolResult(title="multiedit", output="", metadata={})
    return ToolResult(
        title=params.file_path,
        output=final.output,
        metadata={
            "results": [result.metadata for result in results],
        },
    )


MultiEditTool = Tool.define(
    tool_id="multiedit",
    description="Run multiple edit operations sequentially on one file.",
    parameters_type=MultiEditParams,
    execute_fn=multiedit_execute,
    auto_truncate=False,
)

