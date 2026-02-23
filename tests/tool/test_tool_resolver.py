import asyncio
from types import SimpleNamespace

import pytest

from hotaru.tool.resolver import ToolResolver
from tests.helpers import fake_app


def _tools_stub(**overrides):
    async def _noop(**_kw):
        return []
    return SimpleNamespace(get_tool_definitions=overrides.get("get_tool_definitions", _noop))


@pytest.mark.anyio
async def test_resolver_strictifies_mcp_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_defs(**_kwargs):
        return []

    async def fake_mcp_tools():
        return {
            "mcp_demo": {
                "description": "demo",
                "input_schema": {
                    "title": "Demo Input",
                    "type": "object",
                    "properties": {
                        "outer": {
                            "title": "Outer",
                            "anyOf": [
                                {
                                    "title": "OuterValue",
                                    "type": "object",
                                    "properties": {"value": {"type": "string", "title": "Value"}},
                                },
                                {"type": "null"},
                            ],
                            "default": None,
                        }
                    },
                },
            }
        }

    resolver = ToolResolver(app=fake_app(
        started=True,
        tools=_tools_stub(get_tool_definitions=fake_defs),
        mcp=SimpleNamespace(tools=fake_mcp_tools),
    ))

    tools = await resolver.resolve(
        caller_agent="build",
        provider_id="openai",
        model_id="gpt-5",
    )

    mcp = next(item for item in tools if item["function"]["name"] == "mcp_demo")
    assert mcp["function"]["parameters"]["additionalProperties"] is False
    assert "title" not in mcp["function"]["parameters"]
    outer = mcp["function"]["parameters"]["properties"]["outer"]
    assert outer["type"] == "object"
    assert outer["additionalProperties"] is False
    assert "anyOf" not in outer
    assert "default" not in outer
    assert "title" not in outer
    assert "title" not in outer["properties"]["value"]


@pytest.mark.anyio
async def test_resolver_propagates_real_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_defs(**_kwargs):
        return []

    async def fake_mcp_tools():
        raise asyncio.CancelledError("cancelled")

    class _Task:
        def cancelling(self) -> int:
            return 1

    resolver = ToolResolver(app=fake_app(
        started=True,
        tools=_tools_stub(get_tool_definitions=fake_defs),
        mcp=SimpleNamespace(tools=fake_mcp_tools),
    ))
    monkeypatch.setattr("hotaru.tool.resolver.asyncio.current_task", lambda: _Task())

    with pytest.raises(asyncio.CancelledError):
        await resolver.resolve(
            caller_agent="build",
            provider_id="openai",
            model_id="gpt-5",
        )


@pytest.mark.anyio
async def test_resolver_treats_noncancelling_cancelled_error_as_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_defs(**_kwargs):
        return [
            {
                "type": "function",
                "function": {
                    "name": "read",
                    "description": "read",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

    async def fake_mcp_tools():
        raise asyncio.CancelledError("transport failure")

    class _Task:
        def cancelling(self) -> int:
            return 0

    resolver = ToolResolver(app=fake_app(
        started=True,
        tools=_tools_stub(get_tool_definitions=fake_defs),
        mcp=SimpleNamespace(tools=fake_mcp_tools),
    ))
    monkeypatch.setattr("hotaru.tool.resolver.asyncio.current_task", lambda: _Task())

    tools = await resolver.resolve(
        caller_agent="build",
        provider_id="openai",
        model_id="gpt-5",
    )

    assert [item["function"]["name"] for item in tools] == ["read"]


@pytest.mark.anyio
async def test_resolver_skips_mcp_when_subsystem_is_degraded() -> None:
    calls: list[str] = []

    async def fake_defs(**_kwargs):
        return [
            {
                "type": "function",
                "function": {
                    "name": "read",
                    "description": "read",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

    async def fake_mcp_tools():
        calls.append("mcp")
        return {
            "mcp_demo": {
                "description": "demo",
                "input_schema": {"type": "object", "properties": {}},
            }
        }

    resolver = ToolResolver(app=fake_app(
        started=True,
        health={
            "status": "degraded",
            "subsystems": {
                "mcp": {"status": "failed", "critical": True, "error": "offline"},
                "lsp": {"status": "ready", "critical": False, "error": None},
            },
        },
        tools=_tools_stub(get_tool_definitions=fake_defs),
        mcp=SimpleNamespace(tools=fake_mcp_tools),
    ))

    tools = await resolver.resolve(
        caller_agent="build",
        provider_id="openai",
        model_id="gpt-5",
    )

    assert [item["function"]["name"] for item in tools] == ["read"]
    assert calls == []
