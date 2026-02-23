from pathlib import Path

import pytest

from hotaru.core.config import Config, ConfigManager
from hotaru.core.global_paths import GlobalPath
from hotaru.project import Instance
from hotaru.skill.discovery import Discovery
from hotaru.skill.skill import Skill


class _FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        text: str = "",
        payload: dict | None = None,
    ) -> None:
        self.status_code = status_code
        self._text = text
        self._payload = payload

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    @property
    def text(self) -> str:
        return self._text

    def json(self) -> dict:
        if self._payload is None:
            raise ValueError("no json payload")
        return self._payload


class _FakeClient:
    def __init__(self, responses: dict[str, _FakeResponse], *args, **kwargs) -> None:
        self._responses = responses

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url: str) -> _FakeResponse:
        return self._responses.get(url, _FakeResponse(status_code=404))


@pytest.mark.anyio
async def test_discovery_pull_downloads_skill_with_and_without_trailing_slash(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base = "https://example.com/.well-known/skills"
    index_url = f"{base}/index.json"
    skill_md_url = f"{base}/remote-skill/SKILL.md"
    script_url = f"{base}/remote-skill/scripts/demo.txt"

    responses = {
        index_url: _FakeResponse(
            payload={
                "skills": [
                    {
                        "name": "remote-skill",
                        "description": "Remote test skill",
                        "files": ["SKILL.md", "scripts/demo.txt"],
                    }
                ]
            }
        ),
        skill_md_url: _FakeResponse(
            text="---\nname: remote-skill\ndescription: Remote skill\n---\n\n# Remote\n"
        ),
        script_url: _FakeResponse(text="demo"),
    }

    monkeypatch.setattr(Discovery, "cache_dir", staticmethod(lambda: tmp_path / "cache"))
    monkeypatch.setattr(
        "hotaru.skill.discovery.httpx.AsyncClient",
        lambda *args, **kwargs: _FakeClient(responses, *args, **kwargs),
    )

    dirs = await Discovery.pull(base)
    assert len(dirs) == 1
    assert (Path(dirs[0]) / "SKILL.md").is_file()
    assert (Path(dirs[0]) / "scripts" / "demo.txt").is_file()

    dirs_no_slash = await Discovery.pull(base.rstrip("/"))
    assert len(dirs_no_slash) == 1


@pytest.mark.anyio
async def test_discovery_pull_returns_empty_on_invalid_index(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base = "https://example.com/.well-known/skills/"
    responses = {
        f"{base}index.json": _FakeResponse(payload={"not_skills": []}),
    }

    monkeypatch.setattr(Discovery, "cache_dir", staticmethod(lambda: tmp_path / "cache"))
    monkeypatch.setattr(
        "hotaru.skill.discovery.httpx.AsyncClient",
        lambda *args, **kwargs: _FakeClient(responses, *args, **kwargs),
    )

    assert await Discovery.pull(base) == []


@pytest.mark.anyio
async def test_skill_loads_from_config_urls(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    registry = Skill()
    registry.reset()
    home = tmp_path / "home"
    project = tmp_path / "project"
    remote = tmp_path / "remote" / "url-skill"
    remote.mkdir(parents=True, exist_ok=True)
    (remote / "SKILL.md").write_text(
        "---\nname: url-skill\ndescription: Skill from URL\n---\n\n# URL\n",
        encoding="utf-8",
    )

    config = Config.model_validate(
        {
            "skills": {
                "urls": ["https://example.com/.well-known/skills/"],
            }
        }
    )

    async def fake_get(cls):
        return config

    async def fake_pull(cls, url: str):
        return [str(remote)]

    monkeypatch.setattr(ConfigManager, "get", classmethod(fake_get))
    monkeypatch.setattr(ConfigManager, "directories", classmethod(lambda cls: []))
    monkeypatch.setattr(Discovery, "pull", classmethod(fake_pull))
    monkeypatch.setattr(GlobalPath, "home", classmethod(lambda cls: str(home)))
    monkeypatch.setattr(Instance, "directory", classmethod(lambda cls: str(project)))
    monkeypatch.setattr(Instance, "worktree", classmethod(lambda cls: str(project)))

    names = {skill.name for skill in await registry.list()}
    assert "url-skill" in names
