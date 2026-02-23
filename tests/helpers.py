"""Shared test helpers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

from hotaru.core.bus import Bus
from hotaru.runtime import AppContext
from hotaru.runtime.runner import SessionRuntime


def _stub() -> SimpleNamespace:
    """Minimal subsystem stub compatible with AppContext.startup/shutdown."""
    async def _noop(*_a: object, **_kw: object) -> None:
        pass

    return SimpleNamespace(init=_noop, shutdown=_noop, reset=lambda: None, clear_session=_noop)


def _agent_stub(**overrides: Any) -> SimpleNamespace:
    """Stub that satisfies the Agent instance interface."""
    async def _noop(*_a: object, **_kw: object) -> None:
        pass

    async def _default_agent() -> str:
        return "build"

    return SimpleNamespace(
        init=_noop, shutdown=_noop, reset=lambda: None, clear_session=_noop,
        get=overrides.get("get", _noop),
        list=overrides.get("list", _noop),
        default_agent=overrides.get("default_agent", _default_agent),
    )


def _tools_stub() -> SimpleNamespace:
    """Stub that satisfies the ToolRegistry instance interface."""
    async def _noop_defs(**_kw: object) -> list:
        return []

    return SimpleNamespace(
        get=lambda _id: None,
        list=lambda: [],
        ids=lambda: [],
        register=lambda _tool: None,
        execute=_noop_defs,
        get_tool_definitions=_noop_defs,
        reset=lambda: None,
    )


def fake_agents(**overrides: Any) -> SimpleNamespace:
    """Build an agents stub with custom get/list/default_agent."""
    return _agent_stub(**overrides)


def fake_app(**overrides: Any) -> AppContext:
    """Lightweight AppContext with stub subsystems."""
    app = AppContext.__new__(AppContext)
    bus = overrides.pop("bus", Bus())
    app.bus = bus
    app._bus_token = Bus.provide(bus)
    app.permission = overrides.pop("permission", _stub())
    app.question = overrides.pop("question", _stub())
    app.skills = overrides.pop("skills", _stub())
    app.agents = overrides.pop("agents", _agent_stub())
    app.tools = overrides.pop("tools", _tools_stub())
    app.mcp = overrides.pop("mcp", _stub())
    app.lsp = overrides.pop("lsp", _stub())
    app._command_event_unsubscribe = overrides.pop("command_event_unsubscribe", None)
    app.started = overrides.pop("started", False)
    app.health = overrides.pop(
        "health",
        {
            "status": "ready" if app.started else "failed",
            "subsystems": {
                "mcp": {
                    "status": "ready" if app.started else "failed",
                    "critical": True,
                    "error": None if app.started else "runtime not started",
                },
                "lsp": {
                    "status": "ready" if app.started else "failed",
                    "critical": False,
                    "error": None if app.started else "runtime not started",
                },
            },
        },
    )
    app.runner = overrides.pop("runner", SessionRuntime(app.clear_session))
    for key, value in overrides.items():
        object.__setattr__(app, key, value)
    return app


@contextmanager
def create_test_app_context() -> Iterator[AppContext]:
    """Create a test AppContext with explicit lifecycle phases."""
    ctx = AppContext()
    ctx.started = True
    ctx.health = {
        "status": "ready",
        "subsystems": {
            "mcp": {"status": "ready", "critical": True, "error": None},
            "lsp": {"status": "ready", "critical": False, "error": None},
        },
    }
    try:
        yield ctx
    finally:
        ctx.skills.reset()
        ctx.agents.reset()
        ctx.tools.reset()
        ctx.started = False
        ctx.health = {
            "status": "failed",
            "subsystems": {
                "mcp": {"status": "failed", "critical": True, "error": "runtime stopped"},
                "lsp": {"status": "failed", "critical": False, "error": "runtime stopped"},
            },
        }
        ctx.bus.clear()
        Bus.restore(ctx._bus_token)
