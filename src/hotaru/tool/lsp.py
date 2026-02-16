"""Language server protocol tool."""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import quote

from pydantic import BaseModel, Field

from ..lsp import LSP
from .external_directory import assert_external_directory
from .tool import Tool, ToolContext, ToolResult

_OPERATIONS = (
    "goToDefinition",
    "findReferences",
    "hover",
    "documentSymbol",
    "workspaceSymbol",
    "goToImplementation",
    "prepareCallHierarchy",
    "incomingCalls",
    "outgoingCalls",
)


class LspParams(BaseModel):
    """Parameters for LSP requests."""

    operation: Literal[
        "goToDefinition",
        "findReferences",
        "hover",
        "documentSymbol",
        "workspaceSymbol",
        "goToImplementation",
        "prepareCallHierarchy",
        "incomingCalls",
        "outgoingCalls",
    ] = Field(..., description="LSP operation")
    filePath: str = Field(..., description="Absolute or relative file path")
    line: int = Field(..., ge=1, description="1-based line")
    character: int = Field(..., ge=1, description="1-based character")


def _to_file_uri(file_path: str) -> str:
    path = Path(file_path).resolve().as_posix()
    return "file://" + quote(path, safe="/:.")


async def lsp_execute(args: LspParams, ctx: ToolContext) -> ToolResult:
    cwd = Path(str(ctx.extra.get("cwd") or Path.cwd()))
    worktree = Path(str(ctx.extra.get("worktree") or cwd))
    file_path = Path(args.filePath)
    if not file_path.is_absolute():
        file_path = cwd / file_path
    file_path = file_path.resolve()

    await assert_external_directory(ctx, file_path)
    await ctx.ask(permission="lsp", patterns=["*"], always=["*"], metadata={})

    if not file_path.exists() or file_path.is_dir():
        raise FileNotFoundError(f"File not found: {file_path}")
    if not await LSP.has_clients(str(file_path)):
        raise RuntimeError("No LSP server available for this file type.")

    await LSP.touch_file(str(file_path), wait_for_diagnostics=True)
    line = args.line - 1
    character = args.character - 1
    uri = _to_file_uri(str(file_path))

    if args.operation == "goToDefinition":
        result = await LSP.definition(str(file_path), line, character)
    elif args.operation == "findReferences":
        result = await LSP.references(str(file_path), line, character)
    elif args.operation == "hover":
        result = await LSP.hover(str(file_path), line, character)
    elif args.operation == "documentSymbol":
        result = await LSP.document_symbol(uri)
    elif args.operation == "workspaceSymbol":
        result = await LSP.workspace_symbol("")
    else:
        raise RuntimeError(f"LSP operation not yet implemented in hotaru: {args.operation}")

    try:
        rel = str(file_path.relative_to(worktree))
    except ValueError:
        rel = str(file_path)

    output = f"No results found for {args.operation}" if not result else str(result)
    return ToolResult(
        title=f"{args.operation} {rel}:{args.line}:{args.character}",
        output=output,
        metadata={"result": result},
    )


_DESCRIPTION = (Path(__file__).parent / "lsp.txt").read_text(encoding="utf-8")

LspTool = Tool.define(
    tool_id="lsp",
    description=_DESCRIPTION,
    parameters_type=LspParams,
    execute_fn=lsp_execute,
    auto_truncate=True,
)
