"""Session task lifecycle manager."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from contextlib import suppress
from typing import TypeVar

from ..core.bus import Bus
from ..session import SessionStatus, SessionStatusProperties

T = TypeVar("T")


class SessionRuntime:
    """Manages asyncio tasks for active session prompts."""

    __slots__ = ("_tasks", "_clear")

    def __init__(self, clear: Callable[[str], Coroutine[object, object, None]]) -> None:
        self._tasks: dict[str, asyncio.Task[object]] = {}
        self._clear = clear

    async def start(self, session_id: str, coro: Coroutine[object, object, T]) -> T:
        task: asyncio.Task[object] = asyncio.create_task(coro)
        prev = self._tasks.get(session_id)
        if prev and not prev.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            raise ValueError("Session already has an active request")
        self._tasks[session_id] = task
        try:
            await Bus.publish(
                SessionStatus,
                SessionStatusProperties(session_id=session_id, status={"type": "working"}),
            )
            return await task  # type: ignore[return-value]
        except asyncio.CancelledError:
            raise
        finally:
            if self._tasks.get(session_id) is task:
                del self._tasks[session_id]
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            await Bus.publish(
                SessionStatus,
                SessionStatusProperties(session_id=session_id, status={"type": "idle"}),
            )

    async def interrupt(self, session_id: str) -> bool:
        task = self._tasks.pop(session_id, None)
        if not task or task.done():
            return False
        task.cancel()
        await self._clear(session_id)
        with suppress(asyncio.CancelledError):
            await task
        return True

    async def shutdown(self) -> None:
        tasks = list(self._tasks.values())
        self._tasks.clear()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
