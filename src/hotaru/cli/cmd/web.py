"""Web command - start web server for browser clients."""

from __future__ import annotations

import asyncio
import webbrowser
from collections.abc import Awaitable, Callable

from rich.console import Console

from ...server.server import Server
from ...util.log import Log

log = Log.create({"service": "cli.web"})
console = Console()


async def _wait_forever() -> None:
    await asyncio.Future()


async def serve_web(
    *,
    host: str,
    port: int,
    open_browser: bool,
    wait: Callable[[], Awaitable[None]] | None = None,
) -> None:
    info = await Server.start(host=host, port=port)
    console.print(f"[green]Hotaru WebUI[/green] running at {info.url}")
    log.info("web server started", {"host": host, "port": port})

    if open_browser:
        webbrowser.open(info.url)

    block = wait or _wait_forever
    try:
        await block()
    finally:
        await Server.stop()
        log.info("web server stopped", {"host": host, "port": port})


def web_command(*, host: str, port: int, open_browser: bool) -> None:
    try:
        asyncio.run(serve_web(host=host, port=port, open_browser=open_browser))
    except KeyboardInterrupt:
        console.print("\nStopping Hotaru WebUI...")
