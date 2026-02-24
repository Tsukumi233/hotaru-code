"""Helpers for executing logic within an instance context."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TypeVar

from ..core.context import ContextNotFoundError
from .instance import Instance

T = TypeVar("T")


async def run_in_instance(
    *,
    directory: str,
    fn: Callable[[], Awaitable[T]],
    init: Callable[[], Awaitable[object]] | None = None,
) -> T:
    """Run ``fn`` inside the matching project instance context."""
    if init is not None:
        return await Instance.provide(directory=directory, fn=fn, init=init)

    try:
        current = Instance.directory()
    except ContextNotFoundError:
        return await Instance.provide(directory=directory, fn=fn)

    if Path(current).resolve() == Path(directory).resolve():
        return await fn()
    return await Instance.provide(directory=directory, fn=fn)
