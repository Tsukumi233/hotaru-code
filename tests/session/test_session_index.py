from pathlib import Path

import pytest

from hotaru.core.global_paths import GlobalPath
from hotaru.session.session import Session
from hotaru.storage import NotFoundError, Storage


def _setup_storage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(GlobalPath, "data", classmethod(lambda cls: str(data_dir)))
    Storage.reset()


@pytest.mark.anyio
async def test_get_uses_session_index_without_scan(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _setup_storage(monkeypatch, tmp_path)
    session = await Session.create(project_id="p1", agent="build", directory=str(tmp_path))

    async def fail_scan(cls, prefix: list[str]) -> list[list[str]]:
        raise AssertionError(f"unexpected full scan: {prefix}")

    monkeypatch.setattr(Storage, "list", classmethod(fail_scan))
    loaded = await Session.get(session.id)

    assert loaded is not None
    assert loaded.id == session.id
    assert loaded.project_id == "p1"


@pytest.mark.anyio
async def test_get_without_index_returns_none(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _setup_storage(monkeypatch, tmp_path)
    session = await Session.create(project_id="p1", agent="build", directory=str(tmp_path))
    await Storage.remove(["session_index", session.id])

    loaded = await Session.get(session.id)

    assert loaded is None


@pytest.mark.anyio
async def test_delete_removes_session_index(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _setup_storage(monkeypatch, tmp_path)
    session = await Session.create(project_id="p1", agent="build", directory=str(tmp_path))

    deleted = await Session.delete(session.id, project_id="p1")

    assert deleted is True
    with pytest.raises(NotFoundError):
        await Storage.read(["session_index", session.id])
