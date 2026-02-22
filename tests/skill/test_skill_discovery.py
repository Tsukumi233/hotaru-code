from pathlib import Path

import pytest

from hotaru.core.config import Config, ConfigManager
from hotaru.core.global_paths import GlobalPath
from hotaru.project import Instance
from hotaru.skill.skill import Skill


def _write_skill(directory: Path, name: str, description: str, body: str = "# Skill") -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(
        (
            "---\n"
            f"name: {name}\n"
            f"description: {description}\n"
            "---\n\n"
            f"{body}\n"
        ),
        encoding="utf-8",
    )


def _patch_config(
    monkeypatch: pytest.MonkeyPatch,
    *,
    config_data: dict | None = None,
    directories: list[str] | None = None,
) -> None:
    config = Config.model_validate(config_data or {})

    async def fake_get(cls):
        return config

    monkeypatch.setattr(ConfigManager, "get", classmethod(fake_get))
    monkeypatch.setattr(ConfigManager, "directories", classmethod(lambda cls: list(directories or [])))


def _patch_instance(monkeypatch: pytest.MonkeyPatch, directory: Path, worktree: Path) -> None:
    monkeypatch.setattr(Instance, "directory", classmethod(lambda cls: str(directory.resolve())))
    monkeypatch.setattr(Instance, "worktree", classmethod(lambda cls: str(worktree.resolve())))


@pytest.mark.anyio
async def test_discovers_skills_from_opencode_roots(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    Skill.reset()
    home = tmp_path / "home"
    project = tmp_path / "project"

    _write_skill(project / ".opencode" / "skill" / "legacy-skill", "legacy-skill", "Legacy skill")
    _write_skill(project / ".opencode" / "skills" / "plural-skill", "plural-skill", "Plural skill")
    _write_skill(home / ".config" / "opencode" / "skills" / "global-skill", "global-skill", "Global skill")

    _patch_instance(monkeypatch, project, project)
    _patch_config(
        monkeypatch,
        directories=[
            str(project / ".opencode"),
            str(home / ".config" / "opencode"),
        ],
    )
    monkeypatch.setattr(GlobalPath, "home", classmethod(lambda cls: str(home)))

    skills = await Skill.list()
    names = {skill.name for skill in skills}
    assert names == {"legacy-skill", "plural-skill", "global-skill"}

    directories = set(await Skill.directories())
    assert str((project / ".opencode" / "skill" / "legacy-skill").resolve()) in directories
    assert str((project / ".opencode" / "skills" / "plural-skill").resolve()) in directories
    assert str((home / ".config" / "opencode" / "skills" / "global-skill").resolve()) in directories


@pytest.mark.anyio
async def test_discovers_external_and_hotaru_compatible_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    Skill.reset()
    home = tmp_path / "home"
    project = tmp_path / "project"
    nested = project / "src" / "nested"
    nested.mkdir(parents=True, exist_ok=True)

    _write_skill(home / ".claude" / "skills" / "global-claude", "global-claude", "Global claude skill")
    _write_skill(home / ".agents" / "skills" / "global-agent", "global-agent", "Global agent skill")
    _write_skill(home / ".hotaru" / "skills" / "global-hotaru", "global-hotaru", "Global hotaru skill")

    _write_skill(project / ".claude" / "skills" / "local-claude", "local-claude", "Local claude skill")
    _write_skill(project / ".agents" / "skills" / "local-agent", "local-agent", "Local agent skill")
    _write_skill(project / ".hotaru" / "skills" / "local-hotaru", "local-hotaru", "Local hotaru skill")

    _patch_instance(monkeypatch, nested, project)
    _patch_config(monkeypatch, directories=[])
    monkeypatch.setattr(GlobalPath, "home", classmethod(lambda cls: str(home)))

    names = {skill.name for skill in await Skill.list()}
    assert names == {
        "global-claude",
        "global-agent",
        "global-hotaru",
        "local-claude",
        "local-agent",
        "local-hotaru",
    }


@pytest.mark.anyio
async def test_discovers_codex_skill_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    Skill.reset()
    home = tmp_path / "home"
    project = tmp_path / "project"
    nested = project / "src" / "nested"
    nested.mkdir(parents=True, exist_ok=True)

    _write_skill(home / ".codex" / "skills" / "global-codex", "global-codex", "Global codex skill")
    _write_skill(project / ".codex" / "skills" / "local-codex", "local-codex", "Local codex skill")

    _patch_instance(monkeypatch, nested, project)
    _patch_config(monkeypatch, directories=[])
    monkeypatch.setattr(GlobalPath, "home", classmethod(lambda cls: str(home)))

    names = {skill.name for skill in await Skill.list()}
    assert "global-codex" in names
    assert "local-codex" in names


@pytest.mark.anyio
async def test_project_external_scan_stops_at_worktree(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    Skill.reset()
    home = tmp_path / "home"
    outer = tmp_path / "outer"
    worktree = outer / "repo"
    nested = worktree / "a" / "b"
    nested.mkdir(parents=True, exist_ok=True)

    _write_skill(outer / ".claude" / "skills" / "outside-skill", "outside-skill", "Should not be discovered")
    _write_skill(worktree / ".claude" / "skills" / "inside-skill", "inside-skill", "Should be discovered")

    _patch_instance(monkeypatch, nested, worktree)
    _patch_config(monkeypatch, directories=[])
    monkeypatch.setattr(GlobalPath, "home", classmethod(lambda cls: str(home)))

    names = {skill.name for skill in await Skill.list()}
    assert "inside-skill" in names
    assert "outside-skill" not in names


@pytest.mark.anyio
async def test_skips_skills_with_missing_required_frontmatter(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    Skill.reset()
    home = tmp_path / "home"
    project = tmp_path / "project"

    _write_skill(project / ".opencode" / "skills" / "valid-skill", "valid-skill", "Valid")
    broken = project / ".opencode" / "skills" / "broken"
    broken.mkdir(parents=True, exist_ok=True)
    (broken / "SKILL.md").write_text(
        "---\nname: broken\n---\n\nMissing description.\n",
        encoding="utf-8",
    )

    _patch_instance(monkeypatch, project, project)
    _patch_config(monkeypatch, directories=[str(project / ".opencode")])
    monkeypatch.setattr(GlobalPath, "home", classmethod(lambda cls: str(home)))

    names = {skill.name for skill in await Skill.list()}
    assert names == {"valid-skill"}


@pytest.mark.anyio
async def test_project_skill_overrides_global_skill_with_same_name(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    Skill.reset()
    home = tmp_path / "home"
    project = tmp_path / "project"

    _write_skill(home / ".claude" / "skills" / "same-skill", "same-skill", "Global description")
    _write_skill(project / ".claude" / "skills" / "same-skill", "same-skill", "Project description")

    _patch_instance(monkeypatch, project, project)
    _patch_config(monkeypatch, directories=[])
    monkeypatch.setattr(GlobalPath, "home", classmethod(lambda cls: str(home)))

    skill = await Skill.get("same-skill")
    assert skill is not None
    assert skill.description == "Project description"
