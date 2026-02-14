import pytest

from hotaru.core.config import Config, ConfigManager, ExperimentalConfig
from hotaru.tool.registry import ToolRegistry


@pytest.mark.anyio
async def test_registry_prefers_apply_patch_for_gpt_models() -> None:
    ToolRegistry.reset()
    definitions = await ToolRegistry.get_tool_definitions(
        provider_id="openai",
        model_id="gpt-5",
    )
    names = {item["function"]["name"] for item in definitions}
    assert "apply_patch" in names
    assert "edit" not in names
    assert "write" not in names


@pytest.mark.anyio
async def test_registry_exposes_batch_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    ToolRegistry.reset()

    async def fake_get(cls):  # type: ignore[no-untyped-def]
        return Config(experimental=ExperimentalConfig(batch_tool=True, enable_exa=False, plan_mode=False))

    monkeypatch.setattr(ConfigManager, "get", classmethod(fake_get))

    definitions = await ToolRegistry.get_tool_definitions(
        provider_id="openai",
        model_id="claude-sonnet",
    )
    names = {item["function"]["name"] for item in definitions}
    assert "batch" in names

