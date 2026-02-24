"""Application runtime context and lifecycle container."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextvars import Token
from typing import Literal, TypedDict

from ..core.bus import Bus, EventPayload
from ..util.log import Log
from .app_runtime import AppRuntime

log = Log.create({"service": "runtime"})


HealthStatus = Literal["ready", "degraded", "failed"]
NodeStatus = Literal["ready", "failed"]


class NodeHealth(TypedDict):
    status: NodeStatus
    critical: bool
    error: str | None


class AppHealth(TypedDict):
    status: HealthStatus
    subsystems: dict[str, NodeHealth]


class AppContext(AppRuntime):
    """Application-level service container.

    Created once per application lifetime (CLI run, TUI session, or web server)
    and threaded through the entire call graph.  Every subsystem that needs
    Permission, Question, Skill, MCP, or LSP receives this container — never
    a freshly constructed instance.
    """

    __slots__ = (
        "_bus_token",
        "_command_event_unsubscribe",
        "started",
        "health",
    )

    def __init__(self) -> None:
        super().__init__()
        self._bus_token: Token[Bus] | None = None
        self._command_event_unsubscribe: Callable[[], None] | None = None
        self.started = False
        self.health = self._failed_health("runtime not started")

    async def startup(self) -> None:
        if self.started:
            return

        if self._bus_token is None:
            self._bus_token = Bus.provide(self.bus)

        results = await asyncio.gather(
            self._start_node("mcp", self.mcp.init, critical=True),
            self._start_node("lsp", self.lsp.init, critical=False),
        )
        subsystems = {name: node for name, node, _ in results}
        self.health = {
            "status": self._health_status(subsystems),
            "subsystems": subsystems,
        }
        critical = [
            (name, error)
            for name, node, error in results
            if error and node["critical"]
        ]
        if critical:
            await self._rollback_startup(subsystems)
            self.health = {
                "status": "failed",
                "subsystems": self._rolled_back(subsystems),
            }
            detail = ", ".join(f"{name}: {error}" for name, error in critical)
            raise RuntimeError(f"critical startup dependency failed: {detail}")
        if self.health["status"] == "degraded":
            log.warn("runtime started in degraded mode", {"subsystems": subsystems})

        from ..command import CommandEvent
        from ..project import Project

        async def _on_command_executed(payload: EventPayload) -> None:
            name = payload.properties.get("name")
            project_id = payload.properties.get("project_id")
            if name != "init":
                return
            if not isinstance(project_id, str) or not project_id:
                return
            await Project.set_initialized(project_id)

        try:
            self._command_event_unsubscribe = Bus.subscribe(
                CommandEvent.Executed,
                _on_command_executed,
            )
            self.started = True
        except asyncio.CancelledError:
            await self._rollback_startup(subsystems)
            self.health = {
                "status": "failed",
                "subsystems": self._rolled_back(subsystems),
            }
            raise
        except Exception:
            await self._rollback_startup(subsystems)
            self.health = {
                "status": "failed",
                "subsystems": self._rolled_back(subsystems),
            }
            raise

    def subsystem_ready(self, name: str) -> bool:
        if not self.started:
            return False
        node = self.health["subsystems"].get(name)
        if not node:
            return False
        return node["status"] == "ready"

    async def _start_node(
        self,
        name: str,
        init: Callable[[], Awaitable[None]],
        *,
        critical: bool,
    ) -> tuple[str, NodeHealth, Exception | None]:
        try:
            await init()
            return name, {"status": "ready", "critical": critical, "error": None}, None
        except Exception as e:
            node: NodeHealth = {
                "status": "failed",
                "critical": critical,
                "error": str(e),
            }
            level = log.error if critical else log.warn
            level("subsystem init failed", {"subsystem": name, "critical": critical, "error": str(e)})
            return name, node, e

    async def _rollback_startup(self, subsystems: dict[str, NodeHealth]) -> None:
        tasks: list[Awaitable[None]] = []
        if subsystems.get("mcp", {}).get("status") == "ready":
            tasks.append(self.mcp.shutdown())
        if subsystems.get("lsp", {}).get("status") == "ready":
            tasks.append(self.lsp.shutdown())
        if not tasks:
            return
        results = await asyncio.gather(*tasks, return_exceptions=True)
        errors = [str(item) for item in results if isinstance(item, BaseException)]
        if errors:
            log.warn("startup rollback completed with errors", {"errors": errors})

    def _health_status(self, subsystems: dict[str, NodeHealth]) -> HealthStatus:
        if any(node["status"] == "failed" and node["critical"] for node in subsystems.values()):
            return "failed"
        if any(node["status"] == "failed" for node in subsystems.values()):
            return "degraded"
        return "ready"

    def _rolled_back(self, subsystems: dict[str, NodeHealth]) -> dict[str, NodeHealth]:
        result = dict(subsystems)
        for name, node in result.items():
            if node["status"] == "failed":
                continue
            result[name] = {
                "status": "failed",
                "critical": node["critical"],
                "error": "startup rolled back after failure",
            }
        return result

    def _failed_health(self, error: str) -> AppHealth:
        return {
            "status": "failed",
            "subsystems": {
                "mcp": {
                    "status": "failed",
                    "critical": True,
                    "error": error,
                },
                "lsp": {
                    "status": "failed",
                    "critical": False,
                    "error": error,
                },
            },
        }

    async def shutdown(self) -> None:
        from ..project import Instance

        await self.runner.shutdown()
        results = await asyncio.gather(
            self.mcp.shutdown(),
            self.lsp.shutdown(),
            self.permission.shutdown(),
            self.question.shutdown(),
            return_exceptions=True,
        )
        await Instance.dispose_all()
        errors = [r for r in results if isinstance(r, BaseException)]
        if self._command_event_unsubscribe:
            self._command_event_unsubscribe()
            self._command_event_unsubscribe = None
        self.skills.reset()
        self.agents.reset()
        self.tools.reset()
        self.bus.clear()
        if self._bus_token is not None:
            Bus.restore(self._bus_token)
            self._bus_token = None
        self.started = False
        self.health = self._failed_health("runtime stopped")
        if errors:
            log.warn("shutdown completed with errors", {"errors": [str(e) for e in errors]})
