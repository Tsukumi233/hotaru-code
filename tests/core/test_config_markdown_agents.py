from pathlib import Path

import pytest

from hotaru.core.config import ConfigManager
from hotaru.core.global_paths import GlobalPath


@pytest.mark.anyio
async def test_load_markdown_agent_from_project_opencode_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    agent_dir = project_dir / ".opencode" / "agents"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "review.md").write_text(
        "\n".join(
            [
                "---",
                "description: Reviews code quality",
                "mode: subagent",
                "maxSteps: 5",
                "tools:",
                "  bash: false",
                "reasoningEffort: high",
                "---",
                "You are a strict code reviewer.",
            ]
        ),
        encoding="utf-8",
    )

    global_dir = tmp_path / "global-config"
    home_dir = tmp_path / "home"
    global_dir.mkdir(parents=True, exist_ok=True)
    home_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(GlobalPath, "config", classmethod(lambda cls: str(global_dir)))
    monkeypatch.setattr(GlobalPath, "home", classmethod(lambda cls: str(home_dir)))
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.delenv("HOTARU_CONFIG_CONTENT", raising=False)
    monkeypatch.delenv("HOTARU_TEST_MANAGED_CONFIG_DIR", raising=False)

    ConfigManager.reset()
    config = await ConfigManager.load(str(project_dir))

    assert config.agent is not None
    assert "review" in config.agent
    review = config.agent["review"]
    assert review.prompt == "You are a strict code reviewer."
    assert review.mode == "subagent"
    assert review.max_steps == 5
    assert review.tools == {"bash": False}
    assert review.model_extra is not None
    assert review.model_extra.get("reasoningEffort") == "high"
