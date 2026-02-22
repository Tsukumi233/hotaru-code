import json
from pathlib import Path

import pytest

from hotaru.core.config import ConfigManager
from hotaru.core.global_paths import GlobalPath


@pytest.mark.anyio
async def test_config_load_merges_and_deduplicates_instruction_arrays(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    global_dir = tmp_path / "global-config"
    project_dir = tmp_path / "project"
    home_dir = tmp_path / "home"
    managed_dir = tmp_path / "managed-config"
    global_dir.mkdir(parents=True, exist_ok=True)
    project_dir.mkdir(parents=True, exist_ok=True)
    home_dir.mkdir(parents=True, exist_ok=True)

    (global_dir / "hotaru.json").write_text(
        json.dumps(
            {
                "instructions": [
                    "global-instructions.md",
                    "shared-rules.md",
                ]
            }
        ),
        encoding="utf-8",
    )
    (project_dir / "hotaru.json").write_text(
        json.dumps(
            {
                "instructions": [
                    "shared-rules.md",
                    "local-instructions.md",
                ]
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setenv("HOTARU_TEST_HOME", str(home_dir))
    monkeypatch.setenv("HOTARU_TEST_MANAGED_CONFIG_DIR", str(managed_dir))
    monkeypatch.setattr(GlobalPath, "config", classmethod(lambda cls: str(global_dir)))

    ConfigManager.reset()
    config = await ConfigManager.load(str(project_dir))
    instructions = config.instructions or []

    assert instructions == [
        "global-instructions.md",
        "shared-rules.md",
        "local-instructions.md",
    ]


@pytest.mark.anyio
async def test_config_load_maps_tool_aliases_to_permissions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    global_dir = tmp_path / "global-config"
    project_dir = tmp_path / "project"
    home_dir = tmp_path / "home"
    managed_dir = tmp_path / "managed-config"
    global_dir.mkdir(parents=True, exist_ok=True)
    project_dir.mkdir(parents=True, exist_ok=True)
    home_dir.mkdir(parents=True, exist_ok=True)
    managed_dir.mkdir(parents=True, exist_ok=True)

    (project_dir / "hotaru.json").write_text(
        json.dumps(
            {
                "tools": {
                    "apply_patch": False,
                    "ls": False,
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setenv("HOTARU_TEST_HOME", str(home_dir))
    monkeypatch.setenv("HOTARU_TEST_MANAGED_CONFIG_DIR", str(managed_dir))
    monkeypatch.setattr(GlobalPath, "config", classmethod(lambda cls: str(global_dir)))

    ConfigManager.reset()
    config = await ConfigManager.load(str(project_dir))

    assert isinstance(config.permission, dict)
    assert config.permission.get("edit") == "deny"
    assert config.permission.get("list") == "deny"
    assert "apply_patch" not in config.permission
    assert "ls" not in config.permission
