"""Instance-scoped runtime bindings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .instance import Instance
from .state import State

if TYPE_CHECKING:
    from ..runtime import AppContext


@dataclass
class RuntimeScope:
    app: AppContext | None = None


_scope = State.create(lambda: Instance.directory(), RuntimeScope)


def bind_runtime(app: AppContext) -> None:
    """Bind an app runtime to the current instance."""
    entry = _scope()
    if entry.app is None:
        entry.app = app
        return
    if entry.app is app:
        return
    if getattr(entry.app, "started", True) is False:
        entry.app = app
        return
    raise RuntimeError("instance runtime already bound to a different AppContext")


def use_runtime() -> AppContext:
    """Resolve the app runtime bound to the current instance."""
    app = _scope().app
    if app is None:
        raise RuntimeError("No AppContext bound to current instance")
    return app
