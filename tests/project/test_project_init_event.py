import pytest

from hotaru.command import publish_command_executed
from hotaru.core.global_paths import GlobalPath
from hotaru.project import Project
from hotaru.storage import NotFoundError, Storage
from tests.helpers import fake_app


def _setup_storage(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(GlobalPath, "data", classmethod(lambda cls: str(data_dir)))
    Storage.reset()


@pytest.mark.anyio
async def test_init_command_event_marks_project_initialized(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _setup_storage(monkeypatch, tmp_path)
    Project.reset_runtime_state()
    app = fake_app()
    await app.startup()
    try:
        await publish_command_executed(
            name="init",
            project_id="project-1",
            arguments="",
        )
        stored = await Storage.read(["project", "project-1"])
        assert stored["time"]["initialized"] is not None
    finally:
        await app.shutdown()


@pytest.mark.anyio
async def test_non_init_command_event_does_not_mark_project_initialized(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _setup_storage(monkeypatch, tmp_path)
    Project.reset_runtime_state()
    app = fake_app()
    await app.startup()
    try:
        await publish_command_executed(
            name="review",
            project_id="project-2",
            arguments="",
        )
        with pytest.raises(NotFoundError):
            await Storage.read(["project", "project-2"])
    finally:
        await app.shutdown()


@pytest.mark.anyio
async def test_init_subscription_survives_app_context_recreation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _setup_storage(monkeypatch, tmp_path)
    Project.reset_runtime_state()

    app1 = fake_app()
    await app1.startup()
    await app1.shutdown()

    app2 = fake_app()
    await app2.startup()
    try:
        await publish_command_executed(
            name="init",
            project_id="project-3",
            arguments="",
        )
        stored = await Storage.read(["project", "project-3"])
        assert stored["time"]["initialized"] is not None
    finally:
        await app2.shutdown()
