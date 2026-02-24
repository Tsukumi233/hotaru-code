from pydantic import BaseModel
import pytest

from hotaru.tool.registry import ToolRegistry
from hotaru.tool.tool import PermissionSpec, Tool, ToolContext, ToolResult
from tests.helpers import fake_app


class _PermParams(BaseModel):
    value: str


@pytest.mark.anyio
async def test_registry_execute_checks_permissions_before_tool_execution() -> None:
    registry = ToolRegistry()
    events: list[str] = []

    async def run(args: _PermParams, _ctx: ToolContext) -> ToolResult:
        events.append(f"execute:{args.value}")
        return ToolResult(title="ok", output=args.value)

    async def perm(args: _PermParams, _ctx: ToolContext) -> list[PermissionSpec]:
        events.append(f"permission:{args.value}")
        return [
            PermissionSpec(
                permission="perm_probe",
                patterns=[args.value],
                always=[args.value],
                metadata={"source": "test"},
            )
        ]

    registry.register(
        Tool.define(
            tool_id="perm_probe",
            description="permission probe",
            parameters_type=_PermParams,
            execute_fn=run,
            permission_fn=perm,
            auto_truncate=False,
        )
    )

    asks: list[dict[str, object]] = []
    ctx = ToolContext(app=fake_app(tools=registry), session_id="ses", message_id="msg", call_id="call", agent="build")

    async def fake_ask(*, permission, patterns, always=None, metadata=None) -> None:
        asks.append(
            {
                "permission": permission,
                "patterns": patterns,
                "always": always,
                "metadata": metadata,
            }
        )

    ctx.ask = fake_ask  # type: ignore[method-assign]

    out = await registry.execute("perm_probe", {"value": "abc"}, ctx)

    assert out.output == "abc"
    assert events == ["permission:abc", "execute:abc"]
    assert asks == [
        {
            "permission": "perm_probe",
            "patterns": ["abc"],
            "always": ["abc"],
            "metadata": {"source": "test"},
        }
    ]
