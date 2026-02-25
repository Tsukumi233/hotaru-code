from pathlib import Path

import pytest

from hotaru.core.config import Config, ConfigManager
from hotaru.core.global_paths import GlobalPath
from hotaru.session.instruction import InstructionPrompt


def _patch_config(monkeypatch: pytest.MonkeyPatch, data: dict) -> None:
    config = Config.model_validate(data)

    async def fake_load(cls, directory: str = "."):
        return config

    async def fake_get(cls):
        return config

    monkeypatch.setattr(ConfigManager, "load", classmethod(fake_load))
    monkeypatch.setattr(ConfigManager, "get", classmethod(fake_get))


def _patch_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    config_dir = tmp_path / "global-config"
    home_dir = tmp_path / "home"
    config_dir.mkdir(parents=True, exist_ok=True)
    home_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(GlobalPath, "config", classmethod(lambda cls: str(config_dir)))
    monkeypatch.setattr(GlobalPath, "home", classmethod(lambda cls: str(home_dir)))
    monkeypatch.setenv("HOME", str(home_dir))

    for key in [
        "HOTARU_CONFIG_DIR",
        "HOTARU_DISABLE_CLAUDE_CODE",
        "HOTARU_DISABLE_CLAUDE_CODE_PROMPT",
        "HOTARU_DISABLE_PROJECT_CONFIG",
    ]:
        monkeypatch.delenv(key, raising=False)

    return config_dir, home_dir


@pytest.mark.anyio
async def test_local_agents_takes_precedence_over_local_claude(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_config(monkeypatch, {})
    _patch_paths(monkeypatch, tmp_path)

    project_dir = tmp_path / "project"
    nested = project_dir / "subdir" / "nested"
    nested.mkdir(parents=True, exist_ok=True)

    agents = project_dir / "AGENTS.md"
    claude = project_dir / "subdir" / "CLAUDE.md"
    agents.write_text("# project rules", encoding="utf-8")
    claude.write_text("# subdir claude rules", encoding="utf-8")

    paths = await InstructionPrompt.system_paths(str(nested), str(project_dir))

    assert str(agents.resolve()) in paths
    assert str(claude.resolve()) not in paths


@pytest.mark.anyio
async def test_local_claude_fallback_when_agents_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_config(monkeypatch, {})
    _patch_paths(monkeypatch, tmp_path)

    project_dir = tmp_path / "project"
    nested = project_dir / "src"
    nested.mkdir(parents=True, exist_ok=True)

    claude = project_dir / "CLAUDE.md"
    claude.write_text("# fallback rules", encoding="utf-8")

    paths = await InstructionPrompt.system_paths(str(nested), str(project_dir))
    assert str(claude.resolve()) in paths


@pytest.mark.anyio
async def test_disable_claude_code_skips_local_claude_rules(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_config(monkeypatch, {})
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setenv("HOTARU_DISABLE_CLAUDE_CODE", "1")

    project_dir = tmp_path / "project"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "CLAUDE.md").write_text("# claude", encoding="utf-8")

    paths = await InstructionPrompt.system_paths(str(project_dir), str(project_dir))
    assert not any(path.endswith("CLAUDE.md") for path in paths)


@pytest.mark.anyio
async def test_global_rule_precedence_prefers_config_dir_then_global_then_claude(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_config(monkeypatch, {})
    global_dir, home_dir = _patch_paths(monkeypatch, tmp_path)

    profile_dir = tmp_path / "profile"
    project_dir = tmp_path / "project"
    profile_dir.mkdir(parents=True, exist_ok=True)
    project_dir.mkdir(parents=True, exist_ok=True)
    (home_dir / ".claude").mkdir(parents=True, exist_ok=True)

    profile_agents = profile_dir / "AGENTS.md"
    global_agents = global_dir / "AGENTS.md"
    home_claude = home_dir / ".claude" / "CLAUDE.md"
    profile_agents.write_text("# profile", encoding="utf-8")
    global_agents.write_text("# global", encoding="utf-8")
    home_claude.write_text("# home claude", encoding="utf-8")

    monkeypatch.setenv("HOTARU_CONFIG_DIR", str(profile_dir))
    paths = await InstructionPrompt.system_paths(str(project_dir), str(project_dir))

    assert str(profile_agents.resolve()) in paths
    assert str(global_agents.resolve()) not in paths
    assert str(home_claude.resolve()) not in paths


@pytest.mark.anyio
async def test_system_loads_configured_file_and_remote_instructions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    docs_dir = project_dir / "docs"
    src_dir = project_dir / "src"
    docs_dir.mkdir(parents=True, exist_ok=True)
    src_dir.mkdir(parents=True, exist_ok=True)
    instruction_file = docs_dir / "rule.md"
    instruction_file.write_text("Local rule body", encoding="utf-8")

    _patch_config(
        monkeypatch,
        {
            "instructions": [
                "docs/*.md",
                "https://example.com/shared-rules.md",
            ]
        },
    )
    _patch_paths(monkeypatch, tmp_path)

    class _FakeResponse:
        def __init__(self, text: str):
            self.text = text
            self.is_success = True

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url: str):
            return _FakeResponse("Remote rule body")

    monkeypatch.setattr("hotaru.session.instruction.httpx.AsyncClient", _FakeClient)

    blocks = await InstructionPrompt.system(str(src_dir), str(project_dir))

    assert any(f"Instructions from: {instruction_file.resolve()}" in block for block in blocks)
    assert any("Instructions from: https://example.com/shared-rules.md" in block for block in blocks)
