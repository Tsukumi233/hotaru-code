"""TUI command - start the interactive terminal interface."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Optional

from ...server.server import DEFAULT_PORT, Server
from ...tui.app import run_tui_async
from ...util.log import Log

log = Log.create({"service": "cli.tui"})


async def serve_tui(
    *,
    model: Optional[str],
    agent: Optional[str],
    session_id: Optional[str],
    continue_session: bool,
    prompt: Optional[str],
    run: Callable[..., Awaitable[None]] | None = None,
) -> None:
    owns = False
    if Server.info() is None:
        await Server.start(host="127.0.0.1", port=DEFAULT_PORT)
        owns = True

    call = run or run_tui_async
    try:
        await call(
            session_id=session_id,
            initial_prompt=prompt,
            model=model,
            agent=agent,
            continue_session=continue_session,
        )
    finally:
        if owns:
            await Server.stop()


def tui_command(
    model: Optional[str] = None,
    agent: Optional[str] = None,
    session_id: Optional[str] = None,
    continue_session: bool = False,
    prompt: Optional[str] = None,
) -> None:
    """Start the Hotaru Code TUI.

    Args:
        model: Model in format provider/model
        agent: Agent name
        session_id: Session ID to continue
        continue_session: Continue last session
        prompt: Initial prompt to send
    """
    log.info(
        "starting TUI",
        {
            "model": model,
            "agent": agent,
            "session_id": session_id,
            "continue_session": continue_session,
        },
    )

    asyncio.run(
        serve_tui(
            model=model,
            agent=agent,
            session_id=session_id,
            continue_session=continue_session,
            prompt=prompt,
        ),
    )
