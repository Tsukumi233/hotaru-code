"""MCP management CLI commands."""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Optional

import typer
from rich.console import Console

from ...core.bus import Bus
from ...mcp.mcp import BrowserOpenFailed
from ...runtime import AppContext

app = typer.Typer(help="Manage MCP servers")
console = Console()


async def _with_runtime(fn: Callable[[AppContext], Awaitable[None]]) -> None:
    ctx = AppContext()
    try:
        await ctx.startup()
        await fn(ctx)
    finally:
        await ctx.shutdown()


def _status_line(name: str, payload: dict[str, Any]) -> str:
    status = str(payload.get("status") or "unknown")
    error = payload.get("error")
    if isinstance(error, str) and error:
        return f"{name}: {status} ({error})"
    return f"{name}: {status}"


async def _resolve_target(ctx: AppContext, name: Optional[str]) -> str:
    if isinstance(name, str) and name.strip():
        return name.strip()
    status = await ctx.mcp.status()
    names = sorted(status.keys())
    if not names:
        raise ValueError("No MCP servers configured")
    if len(names) == 1:
        return names[0]
    raise ValueError("Specify MCP server name")


@app.command("status")
def status_command() -> None:
    """Show status for all configured MCP servers."""

    async def run(ctx: AppContext) -> None:
        status = await ctx.mcp.status()
        if not status:
            console.print("No MCP servers configured")
            return
        for name in sorted(status.keys()):
            console.print(_status_line(name, status[name].model_dump()))

    asyncio.run(_with_runtime(run))


@app.command("auth")
def auth_command(
    name: Optional[str] = typer.Argument(default=None, help="MCP server name"),
) -> None:
    """Authenticate an OAuth-enabled MCP server."""

    async def run(ctx: AppContext) -> None:
        target = await _resolve_target(ctx, name)
        if not await ctx.mcp.supports_oauth(target):
            raise ValueError(f"MCP server {target} does not support OAuth")

        def on_browser_open_failed(event) -> None:
            props = event.properties if hasattr(event, "properties") else {}
            if props.get("mcp_name") != target:
                return
            url = str(props.get("url") or "").strip()
            if not url:
                return
            console.print("Open this URL manually to continue OAuth:")
            console.print(url)

        unsubscribe: Callable[[], None] = lambda: None
        try:
            unsubscribe = Bus.subscribe(BrowserOpenFailed, on_browser_open_failed)
        except RuntimeError:
            pass
        try:
            result = await ctx.mcp.authenticate(target)
        finally:
            unsubscribe()
        console.print(_status_line(target, result.model_dump()))

    try:
        asyncio.run(_with_runtime(run))
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


@app.command("logout")
def logout_command(
    name: Optional[str] = typer.Argument(default=None, help="MCP server name"),
) -> None:
    """Remove stored OAuth credentials for an MCP server."""

    async def run(ctx: AppContext) -> None:
        target = await _resolve_target(ctx, name)
        await ctx.mcp.remove_auth(target)
        console.print(f"Removed OAuth credentials for {target}")

    try:
        asyncio.run(_with_runtime(run))
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


@app.command("connect")
def connect_command(
    name: str = typer.Argument(..., help="MCP server name"),
) -> None:
    """Connect an MCP server."""

    async def run(ctx: AppContext) -> None:
        await ctx.mcp.connect(name, use_oauth=True)
        status = await ctx.mcp.status()
        payload = status.get(name)
        if payload is None:
            console.print(f"{name}: disabled")
            return
        console.print(_status_line(name, payload.model_dump()))

    try:
        asyncio.run(_with_runtime(run))
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


@app.command("disconnect")
def disconnect_command(
    name: str = typer.Argument(..., help="MCP server name"),
) -> None:
    """Disconnect an MCP server."""

    async def run(ctx: AppContext) -> None:
        await ctx.mcp.disconnect(name)
        console.print(f"{name}: disconnected")

    try:
        asyncio.run(_with_runtime(run))
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
