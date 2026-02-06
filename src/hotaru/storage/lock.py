"""Reader-writer lock for concurrent file access.

Provides async reader-writer locks following the same pattern as
OpenCode's Lock utility. Writers are prioritized to prevent starvation.
"""

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict


class _LockState:
    __slots__ = ("readers", "writer", "waiting_readers", "waiting_writers")

    def __init__(self):
        self.readers: int = 0
        self.writer: bool = False
        self.waiting_readers: list[asyncio.Future] = []
        self.waiting_writers: list[asyncio.Future] = []


class Lock:
    """Async reader-writer lock keyed by string."""

    _locks: Dict[str, _LockState] = {}

    @classmethod
    def _get(cls, key: str) -> _LockState:
        if key not in cls._locks:
            cls._locks[key] = _LockState()
        return cls._locks[key]

    @classmethod
    def _process(cls, key: str) -> None:
        state = cls._locks.get(key)
        if not state or state.writer or state.readers > 0:
            return

        # Prioritize writers to prevent starvation
        if state.waiting_writers:
            fut = state.waiting_writers.pop(0)
            if not fut.done():
                fut.set_result(None)
            return

        # Wake all waiting readers
        while state.waiting_readers:
            fut = state.waiting_readers.pop(0)
            if not fut.done():
                fut.set_result(None)

        # Clean up empty lock entries
        if (
            state.readers == 0
            and not state.writer
            and not state.waiting_readers
            and not state.waiting_writers
        ):
            cls._locks.pop(key, None)

    @classmethod
    @asynccontextmanager
    async def read(cls, key: str) -> AsyncIterator[None]:
        """Acquire a read lock. Multiple concurrent readers allowed."""
        state = cls._get(key)
        loop = asyncio.get_running_loop()

        if not state.writer and not state.waiting_writers:
            state.readers += 1
        else:
            fut = loop.create_future()
            state.waiting_readers.append(fut)
            await fut
            state.readers += 1

        try:
            yield
        finally:
            state.readers -= 1
            cls._process(key)

    @classmethod
    @asynccontextmanager
    async def write(cls, key: str) -> AsyncIterator[None]:
        """Acquire an exclusive write lock."""
        state = cls._get(key)
        loop = asyncio.get_running_loop()

        if not state.writer and state.readers == 0:
            state.writer = True
        else:
            fut = loop.create_future()
            state.waiting_writers.append(fut)
            await fut
            state.writer = True

        try:
            yield
        finally:
            state.writer = False
            cls._process(key)
