from pathlib import Path

import pytest

from hotaru.core.global_paths import GlobalPath
from hotaru.project import Project
from hotaru.storage import Storage


def _setup_storage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(GlobalPath, "data", classmethod(lambda cls: str(data_dir)))
    Storage.reset()
    Project.reset_runtime_state()


@pytest.mark.anyio
async def test_from_directory_uses_persisted_project_record(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _setup_storage(monkeypatch, tmp_path)

    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    await Storage.write(
        ["project", "global"],
        {
            "id": "global",
            "worktree": "/",
            "sandboxes": ["/does/not/exist"],
            "time": {
                "created": 100,
                "updated": 200,
                "initialized": 300,
            },
        },
    )

    project, sandbox = await Project.from_directory(str(workspace))

    assert project.id == "global"
    assert sandbox == "/"
    assert project.time.initialized == 300
    assert project.sandboxes == []

    stored = await Storage.read(["project", "global"])
    assert stored["time"]["initialized"] == 300
    assert stored["sandboxes"] == []


@pytest.mark.anyio
async def test_add_and_remove_sandbox_persist(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _setup_storage(monkeypatch, tmp_path)

    sandbox = tmp_path / "sandbox-a"
    sandbox.mkdir(parents=True, exist_ok=True)

    await Storage.write(
        ["project", "project-1"],
        {
            "id": "project-1",
            "worktree": str(tmp_path),
            "sandboxes": [],
            "time": {
                "created": 100,
                "updated": 100,
            },
        },
    )

    added = await Project.add_sandbox("project-1", str(sandbox))
    assert added is not None
    assert str(sandbox) in added.sandboxes

    stored_after_add = await Storage.read(["project", "project-1"])
    assert str(sandbox) in stored_after_add["sandboxes"]

    removed = await Project.remove_sandbox("project-1", str(sandbox))
    assert removed is not None
    assert str(sandbox) not in removed.sandboxes

    stored_after_remove = await Storage.read(["project", "project-1"])
    assert str(sandbox) not in stored_after_remove["sandboxes"]


@pytest.mark.anyio
async def test_set_initialized_creates_record_if_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _setup_storage(monkeypatch, tmp_path)

    await Project.set_initialized("missing-project")

    stored = await Storage.read(["project", "missing-project"])
    assert stored["time"]["initialized"] is not None
