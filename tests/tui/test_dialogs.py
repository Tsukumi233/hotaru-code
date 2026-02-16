from types import SimpleNamespace

import pytest
from textual.widgets import ListView

from hotaru.tui.app import (
    _parse_model_ids,
    _resolve_provider_preset,
    _validate_base_url,
    _validate_provider_id,
)
from hotaru.tui.dialogs import ModelSelectDialog


def _compose_model_list(dialog: ModelSelectDialog):
    container = list(dialog.compose())[0]
    list_view = next(
        child
        for child in container._pending_children
        if isinstance(child, ListView)
    )
    return list_view._pending_children


def test_model_select_dialog_uses_safe_option_ids() -> None:
    dialog = ModelSelectDialog(
        providers={
            "xingyeai": [
                {"id": "claude-sonnet-4.5", "name": "claude-sonnet-4.5"},
                {"id": "claude-opus-4-6", "name": "claude-opus-4-6"},
            ]
        }
    )

    items = _compose_model_list(dialog)
    ids = [item.id for item in items if item.id]
    assert ids == ["model-option-0", "model-option-1"]


def test_model_select_dialog_returns_original_model_id() -> None:
    dialog = ModelSelectDialog(
        providers={
            "xingyeai": [
                {"id": "claude-sonnet-4.5", "name": "claude-sonnet-4.5"},
            ]
        }
    )
    list(dialog.compose())

    selected = []
    dialog.dismiss = lambda result: selected.append(result)
    dialog.on_list_view_selected(
        SimpleNamespace(item=SimpleNamespace(id="model-option-0"))
    )

    assert selected == [("xingyeai", "claude-sonnet-4.5")]


def test_validate_provider_id_pattern() -> None:
    assert _validate_provider_id("XingyeAI_01") == "xingyeai_01"
    with pytest.raises(ValueError):
        _validate_provider_id("bad.provider")


def test_validate_base_url_requires_http_scheme() -> None:
    assert _validate_base_url("https://api.example.com/v1") == "https://api.example.com/v1"
    with pytest.raises(ValueError):
        _validate_base_url("api.example.com/v1")


def test_parse_model_ids_rejects_whitespace_and_deduplicates() -> None:
    assert _parse_model_ids("claude-sonnet-4.5, claude-sonnet-4.5, test") == [
        "claude-sonnet-4.5",
        "test",
    ]
    with pytest.raises(ValueError):
        _parse_model_ids("claude sonnet-4.5")


def test_moonshot_provider_preset_defaults() -> None:
    preset = _resolve_provider_preset("moonshot")
    assert preset is not None
    assert preset.provider_type == "openai"
    assert preset.provider_id == "moonshot"
    assert preset.base_url == "https://api.moonshot.cn/v1"
    assert preset.default_models == "kimi-k2.5"
