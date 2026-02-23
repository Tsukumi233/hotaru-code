from pathlib import Path

import pytest

from hotaru.app_services.session_service import SessionService
from hotaru.core.bus import Bus
from hotaru.core.global_paths import GlobalPath
from hotaru.session import Session
from hotaru.storage import Storage
from tests.helpers import fake_app


def _setup_storage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(GlobalPath, "data", classmethod(lambda cls: str(data)))
    Storage.reset()
    Bus.provide(Bus())


@pytest.mark.anyio
async def test_create_defaults_title(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _setup_storage(monkeypatch, tmp_path)

    created = await SessionService.create({"project_id": "p1"}, str(tmp_path), app=fake_app())

    assert created["title"] == "New Session"
    saved = await Session.get(created["id"], project_id="p1")
    assert saved is not None and saved.title == "New Session"


@pytest.mark.anyio
async def test_create_uses_explicit_title(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _setup_storage(monkeypatch, tmp_path)

    created = await SessionService.create({"project_id": "p1", "title": "  Demo  "}, str(tmp_path), app=fake_app())

    assert created["title"] == "Demo"
    saved = await Session.get(created["id"], project_id="p1")
    assert saved is not None and saved.title == "Demo"


@pytest.mark.anyio
async def test_list_get_update_always_include_title(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _setup_storage(monkeypatch, tmp_path)
    session = await Session.create(project_id="p1", agent="build", directory=str(tmp_path))

    listed = await SessionService.list("p1", str(tmp_path))
    fetched = await SessionService.get(session.id)
    updated = await SessionService.update(session.id, {"title": "Renamed"})

    assert listed[0]["title"] == "New Session"
    assert fetched is not None and fetched["title"] == "New Session"
    assert updated is not None and updated["title"] == "Renamed"
