"""Reader-writer lock for concurrent file access.

Provides async reader-writer locks following the same pattern as
OpenCode's Lock utility. Writers are prioritized to prevent starvation.
"""

import asyncio
import os
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, BinaryIO, Dict


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

    @staticmethod
    def _lock_file(key: str) -> str:
        return f"{key}.lock"

    @staticmethod
    def _lock_handle(path: str) -> BinaryIO:
        lock = Path(path)
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.touch(exist_ok=True)
        file = open(lock, "r+b")
        if os.name == "nt":
            file.seek(0, os.SEEK_END)
            if file.tell() == 0:
                file.write(b"\0")
                file.flush()
        return file

    @staticmethod
    def _os_lock(handle: BinaryIO, shared: bool) -> None:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            return

        import fcntl

        flag = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
        fcntl.flock(handle.fileno(), flag)

    @staticmethod
    def _os_unlock(handle: BinaryIO) -> None:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            return

        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @classmethod
    async def _acquire_process(cls, key: str, *, shared: bool) -> BinaryIO:
        handle = cls._lock_handle(cls._lock_file(key))
        try:
            await asyncio.to_thread(cls._os_lock, handle, shared)
        except Exception:
            handle.close()
            raise
        return handle

    @classmethod
    async def _release_process(cls, handle: BinaryIO) -> None:
        try:
            await asyncio.to_thread(cls._os_unlock, handle)
        finally:
            handle.close()

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
        process_lock: BinaryIO | None = None

        if not state.writer and not state.waiting_writers:
            state.readers += 1
        else:
            fut = loop.create_future()
            state.waiting_readers.append(fut)
            await fut
            state.readers += 1

        try:
            process_lock = await cls._acquire_process(key, shared=True)
            yield
        finally:
            if process_lock:
                await cls._release_process(process_lock)
            state.readers -= 1
            cls._process(key)

    @classmethod
    @asynccontextmanager
    async def write(cls, key: str) -> AsyncIterator[None]:
        """Acquire an exclusive write lock."""
        state = cls._get(key)
        loop = asyncio.get_running_loop()
        process_lock: BinaryIO | None = None

        if not state.writer and state.readers == 0:
            state.writer = True
        else:
            fut = loop.create_future()
            state.waiting_writers.append(fut)
            await fut
            state.writer = True

        try:
            process_lock = await cls._acquire_process(key, shared=False)
            yield
        finally:
            if process_lock:
                await cls._release_process(process_lock)
            state.writer = False
            cls._process(key)

    @classmethod
    @asynccontextmanager
    async def write_many(cls, keys: list[str]) -> AsyncIterator[None]:
        """Acquire exclusive locks for multiple keys in a deadlock-safe order."""
        unique = sorted(set(keys))
        async with AsyncExitStack() as stack:
            for key in unique:
                await stack.enter_async_context(cls.write(key))
            yield
