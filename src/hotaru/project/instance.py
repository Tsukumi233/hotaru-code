"""Instance context management.

Provides scoped execution context for project operations.
Each instance represents an active working directory with its associated project.
"""

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional, TypeVar

from ..core.bus import Bus, InstanceDisposed
from ..core.context import Context
from ..util.log import Log
from .project import Project, ProjectInfo
from .state import State

log = Log.create({"service": "instance"})

R = TypeVar('R')


@dataclass
class InstanceContext:
    """Context data for an instance."""
    directory: str
    worktree: str
    project: ProjectInfo


# Create the instance context
_context: Context[InstanceContext] = Context.create("instance")

# Cache of initialized instances
_cache: Dict[str, asyncio.Task[InstanceContext]] = {}

# Track disposal state
_disposal_all: Optional[asyncio.Task[None]] = None


def _contains_path(base: str, target: str) -> bool:
    """Check if target path is contained within base path."""
    try:
        base_path = Path(base).resolve()
        target_path = Path(target).resolve()
        return target_path.is_relative_to(base_path)
    except (ValueError, OSError):
        return False


class Instance:
    """Instance context manager.

    Provides scoped execution for project operations. Each unique working
    directory gets its own instance with cached project information.

    Example:
        async def main():
            result = await Instance.provide(
                directory="/path/to/project",
                fn=lambda: do_work()
            )

        # Inside the context:
        print(Instance.directory())  # Current working directory
        print(Instance.project().id)  # Project ID
    """

    @classmethod
    async def provide(
        cls,
        directory: str,
        fn: Callable[[], R | Awaitable[R]],
        init: Optional[Callable[[], Awaitable[Any]]] = None
    ) -> R:
        """Execute a function within an instance context.

        Args:
            directory: Working directory for this instance
            fn: Function to execute (sync or async)
            init: Optional initialization function called once per instance

        Returns:
            Result of fn
        """
        existing = _cache.get(directory)

        if not existing:
            log.info("creating instance", {"directory": directory})

            async def create_context() -> InstanceContext:
                project, sandbox = await Project.from_directory(directory)
                ctx = InstanceContext(
                    directory=directory,
                    worktree=sandbox,
                    project=project
                )

                if init:
                    await _context.provide(ctx, init)

                return ctx

            existing = asyncio.create_task(create_context())
            _cache[directory] = existing

        ctx = await existing
        return await _context.provide(ctx, fn)

    @classmethod
    def directory(cls) -> str:
        """Get current instance directory."""
        return _context.use().directory

    @classmethod
    def worktree(cls) -> str:
        """Get current instance worktree."""
        return _context.use().worktree

    @classmethod
    def project(cls) -> ProjectInfo:
        """Get current instance project."""
        return _context.use().project

    @classmethod
    def contains_path(cls, filepath: str) -> bool:
        """Check if a path is within the project boundary.

        Returns True if path is inside Instance.directory() OR Instance.worktree().
        Paths within the worktree but outside the working directory should not
        trigger external_directory permission.

        Args:
            filepath: Path to check

        Returns:
            True if path is within project boundary
        """
        if _contains_path(cls.directory(), filepath):
            return True

        # Non-git projects set worktree to "/" which would match ANY absolute path.
        # Skip worktree check in this case to preserve external_directory permissions.
        if cls.worktree() == "/":
            return False

        return _contains_path(cls.worktree(), filepath)

    @classmethod
    def state(
        cls,
        init: Callable[[], R],
        dispose: Optional[Callable[[R], Awaitable[None]]] = None
    ) -> Callable[[], R]:
        """Create instance-scoped state.

        Args:
            init: Factory function to create the state
            dispose: Optional cleanup function

        Returns:
            Accessor function for the state
        """
        return State.create(lambda: cls.directory(), init, dispose)

    @classmethod
    async def dispose(cls) -> None:
        """Dispose the current instance."""
        directory = cls.directory()
        log.info("disposing instance", {"directory": directory})

        await State.dispose(directory)

        if directory in _cache:
            del _cache[directory]

        await Bus.publish(InstanceDisposed, {"directory": directory})

    @classmethod
    async def dispose_all(cls) -> None:
        """Dispose all instances."""
        global _disposal_all

        if _disposal_all:
            return await _disposal_all

        async def do_dispose_all():
            log.info("disposing all instances")

            entries = list(_cache.items())

            for key, task in entries:
                if _cache.get(key) is not task:
                    continue

                try:
                    ctx = await task
                except Exception as error:
                    log.warn("instance dispose failed", {"key": key, "error": error})
                    if _cache.get(key) is task:
                        del _cache[key]
                    continue

                if _cache.get(key) is not task:
                    continue

                await _context.provide(ctx, cls.dispose)

        try:
            _disposal_all = asyncio.create_task(do_dispose_all())
            await _disposal_all
        finally:
            _disposal_all = None
