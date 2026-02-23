import pytest

from hotaru.core.config import Config, ConfigManager, ExperimentalConfig
from hotaru.tool.registry import ToolRegistry
from tests.helpers import fake_app


@pytest.mark.anyio
async def test_registry_prefers_apply_patch_for_gpt_models() -> None:
    registry = ToolRegistry()
    definitions = await registry.get_tool_definitions(
        app=fake_app(tools=registry),
        provider_id="openai",
        model_id="gpt-5",
    )
    names = {item["function"]["name"] for item in definitions}
    assert "apply_patch" in names
    assert "edit" not in names
    assert "write" not in names


@pytest.mark.anyio
async def test_registry_exposes_batch_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = ToolRegistry()

    async def fake_get(cls):  # type: ignore[no-untyped-def]
        return Config(experimental=ExperimentalConfig(batch_tool=True, enable_exa=False, plan_mode=False))

    monkeypatch.setattr(ConfigManager, "get", classmethod(fake_get))

    definitions = await registry.get_tool_definitions(
        app=fake_app(tools=registry),
        provider_id="openai",
        model_id="claude-sonnet",
    )
    names = {item["function"]["name"] for item in definitions}
    assert "batch" in names


@pytest.mark.anyio
async def test_registry_keeps_plan_tools_visible_when_plan_flag_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = ToolRegistry()

    async def fake_get(cls):  # type: ignore[no-untyped-def]
        return Config(experimental=ExperimentalConfig(plan_mode=False, batch_tool=False, enable_exa=False))

    monkeypatch.setattr(ConfigManager, "get", classmethod(fake_get))

    definitions = await registry.get_tool_definitions(
        app=fake_app(tools=registry),
        provider_id="openai",
        model_id="gpt-5",
    )
    names = {item["function"]["name"] for item in definitions}
    assert "plan_enter" in names
    assert "plan_exit" in names


@pytest.mark.anyio
async def test_registry_strictifies_builtin_tool_schema() -> None:
    registry = ToolRegistry()
    definitions = await registry.get_tool_definitions(
        app=fake_app(tools=registry),
        provider_id="openai",
        model_id="gpt-5",
    )
    read_tool = next(item for item in definitions if item["function"]["name"] == "read")
    params = read_tool["function"]["parameters"]
    assert params["type"] == "object"
    assert params["additionalProperties"] is False
    assert "title" not in params
    assert "title" not in params["properties"]["filePath"]

    offset = params["properties"]["offset"]
    assert offset["type"] == "integer"
    assert "anyOf" not in offset
    assert "default" not in offset
    assert "title" not in offset

    limit = params["properties"]["limit"]
    assert limit["type"] == "integer"
    assert "anyOf" not in limit
    assert "default" not in limit
    assert "title" not in limit
