"""Debug CLI commands."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, Optional

import typer
from pydantic import BaseModel

from ...lsp import LSP
from ...project.instance import Instance

app = typer.Typer(help="Debugging utilities")
lsp_app = typer.Typer(help="LSP debugging utilities")
app.add_typer(lsp_app, name="lsp", help="LSP debugging utilities")


def _json_default(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


async def collect_lsp_diagnostics(
    file_path: str,
    *,
    cwd: Optional[str] = None,
    pause_seconds: float = 1.0,
) -> Dict[str, Any]:
    """Collect diagnostics for a file in the current instance context."""
    directory = str(Path(cwd or Path.cwd()).resolve())
    target = Path(file_path)
    if not target.is_absolute():
        target = Path(directory) / target
    target = target.resolve()

    async def run() -> Dict[str, Any]:
        try:
            await LSP.touch_file(str(target), wait_for_diagnostics=True)
            await asyncio.sleep(pause_seconds)
            return await LSP.diagnostics()
        finally:
            await LSP.shutdown()

    return await Instance.provide(directory=directory, fn=run)


@lsp_app.command("diagnostics")
def diagnostics_command(
    file: str = typer.Argument(..., help="File path to query diagnostics for"),
) -> None:
    """Get diagnostics for a file."""
    payload = asyncio.run(collect_lsp_diagnostics(file))
    typer.echo(json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default))
