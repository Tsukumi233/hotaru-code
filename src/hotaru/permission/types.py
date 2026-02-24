"""Protocol types for permission dependency injection."""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class ProjectResolver(Protocol):
    """Resolves a session ID to its project ID.

    Injected into Permission to avoid circular imports with session.
    """

    async def __call__(self, session_id: str) -> Optional[str]: ...


@runtime_checkable
class ScopeResolver(Protocol):
    """Resolves the current permission memory scope.

    Injected into Permission to avoid circular imports with config.
    """

    async def __call__(self) -> str: ...
