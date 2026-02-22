import asyncio

import pytest

from hotaru.tool.resolver import ToolResolver


@pytest.mark.anyio
async def test_resolver_strictifies_mcp_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_defs(cls, **_kwargs):
        return []

    async def fake_mcp_tools(cls):
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

    monkeypatch.setattr("hotaru.tool.resolver.ToolRegistry.get_tool_definitions", classmethod(fake_defs))
    monkeypatch.setattr("hotaru.mcp.MCP.tools", classmethod(fake_mcp_tools))

    tools = await ToolResolver.resolve(
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
    async def fake_defs(cls, **_kwargs):
        return []

    async def fake_mcp_tools(cls):
        raise asyncio.CancelledError("cancelled")

    class _Task:
        def cancelling(self) -> int:
            return 1

    monkeypatch.setattr("hotaru.tool.resolver.ToolRegistry.get_tool_definitions", classmethod(fake_defs))
    monkeypatch.setattr("hotaru.mcp.MCP.tools", classmethod(fake_mcp_tools))
    monkeypatch.setattr("hotaru.tool.resolver.asyncio.current_task", lambda: _Task())

    with pytest.raises(asyncio.CancelledError):
        await ToolResolver.resolve(
            caller_agent="build",
            provider_id="openai",
            model_id="gpt-5",
        )


@pytest.mark.anyio
async def test_resolver_treats_noncancelling_cancelled_error_as_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_defs(cls, **_kwargs):
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

    async def fake_mcp_tools(cls):
        raise asyncio.CancelledError("transport failure")

    class _Task:
        def cancelling(self) -> int:
            return 0

    monkeypatch.setattr("hotaru.tool.resolver.ToolRegistry.get_tool_definitions", classmethod(fake_defs))
    monkeypatch.setattr("hotaru.mcp.MCP.tools", classmethod(fake_mcp_tools))
    monkeypatch.setattr("hotaru.tool.resolver.asyncio.current_task", lambda: _Task())

    tools = await ToolResolver.resolve(
        caller_agent="build",
        provider_id="openai",
        model_id="gpt-5",
    )

    assert [item["function"]["name"] for item in tools] == ["read"]
