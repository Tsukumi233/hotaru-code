import pytest
from pydantic import ValidationError

from hotaru.core.config import Config, PermissionMemoryScope


def test_config_defaults_are_typed_models() -> None:
    config = Config.model_validate({})

    assert config.skills.paths == []
    assert config.skills.urls == []
    assert config.experimental.batch_tool is False
    assert config.experimental.enable_exa is False
    assert config.experimental.lsp_tool is False
    assert config.experimental.plan_mode is False
    assert config.experimental.primary_tools == []
    assert config.permission_memory_scope == PermissionMemoryScope.SESSION
    assert config.continue_loop_on_deny is False


def test_config_forbids_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Config.model_validate({"unknown": 1})

    with pytest.raises(ValidationError):
        Config.model_validate({"experimental": {"unknown": True}})
