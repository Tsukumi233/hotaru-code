from pathlib import Path

import pytest

from hotaru.core.global_paths import GlobalPath
from hotaru.session.todo import Todo, TodoInfo
from hotaru.storage import Storage


def _setup_storage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(GlobalPath, "data", classmethod(lambda cls: str(data_dir)))
    Storage.reset()


@pytest.mark.anyio
async def test_todo_update_and_get_roundtrip(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _setup_storage(monkeypatch, tmp_path)

    todos = [
        TodoInfo(content="Implement parser", status="in_progress", priority="high", id="t1"),
        TodoInfo(content="Write tests", status="pending", priority="medium", id="t2"),
    ]
    await Todo.update(session_id="session_1", todos=todos)

    loaded = await Todo.get("session_1")
    assert [item.id for item in loaded] == ["t1", "t2"]
    assert loaded[0].status == "in_progress"

