"""Invalid tool placeholder."""

from pydantic import BaseModel, Field

from .tool import Tool, ToolContext, ToolResult


class InvalidParams(BaseModel):
    """Parameters for invalid tool."""

    tool: str = Field(..., description="Invalid tool name")
    error: str = Field(..., description="Validation error detail")


async def invalid_execute(params: InvalidParams, _ctx: ToolContext) -> ToolResult:
    return ToolResult(
        title="Invalid Tool",
        output=f"The arguments provided to the tool are invalid: {params.error}",
        metadata={"tool": params.tool},
    )


InvalidTool = Tool.define(
    tool_id="invalid",
    description="Do not use.",
    parameters_type=InvalidParams,
    execute_fn=invalid_execute,
    auto_truncate=False,
)

