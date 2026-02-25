import asyncio
import json
import multiprocessing as mp
import os
import time
from pathlib import Path

import pytest

from hotaru.core.global_paths import GlobalPath
from hotaru.storage import NotFoundError, Storage


def _setup_storage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(GlobalPath, "data", classmethod(lambda cls: str(data_dir)))
    Storage.reset()
    return data_dir


def _worker(data_home: str, loops: int) -> None:
    os.environ["XDG_DATA_HOME"] = data_home
    Storage.reset()

    async def run() -> None:
        await Storage.initialize()
        for _ in range(loops):
            await Storage.update(
                ["counter", "shared"],
                lambda d: d.__setitem__("n", int(d.get("n", 0)) + 1),
            )
        Storage.close()

    asyncio.run(run())


@pytest.mark.anyio
async def test_transaction_put_delete_roundtrip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _setup_storage(monkeypatch, tmp_path)

    await Storage.initialize()
    await Storage.write(["doc", "a"], {"v": 1})
    await Storage.write(["doc", "b"], {"v": 2})
    await Storage.transaction(
        [
            Storage.put(["doc", "a"], {"v": 10}),
            Storage.delete(["doc", "b"]),
        ]
    )

    assert await Storage.read(["doc", "a"]) == {"v": 10}
    with pytest.raises(NotFoundError):
        await Storage.read(["doc", "b"])
    Storage.close()


@pytest.mark.anyio
async def test_json_migration_on_initialize(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verify that existing JSON files are migrated to SQLite on first init."""
    data_dir = _setup_storage(monkeypatch, tmp_path)

    # Create a JSON file in the old storage layout
    json_dir = data_dir / "storage" / "doc"
    json_dir.mkdir(parents=True, exist_ok=True)
    (json_dir / "a.json").write_text('{"v": 42}', encoding="utf-8")

    await Storage.initialize()
    assert await Storage.read(["doc", "a"]) == {"v": 42}
    Storage.close()


@pytest.mark.anyio
async def test_initialize_idempotent_when_called_concurrently(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _setup_storage(monkeypatch, tmp_path)

    paths = await asyncio.gather(*(Storage.initialize() for _ in range(8)))
    assert len(set(paths)) == 1
    Storage.close()


def test_cross_process_update_is_serialized(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    data_home = tmp_path / "xdg"
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    Storage.reset()

    async def setup() -> None:
        await Storage.initialize()
        await Storage.write(["counter", "shared"], {"n": 0})
        Storage.close()

    asyncio.run(setup())

    ctx = mp.get_context("spawn")
    jobs = [ctx.Process(target=_worker, args=(str(data_home), 60)) for _ in range(4)]
    for job in jobs:
        job.start()
    for job in jobs:
        job.join(timeout=30)
        assert job.exitcode == 0

    async def verify() -> dict:
        Storage.reset()
        await Storage.initialize()
        result = await Storage.read(["counter", "shared"])
        Storage.close()
        return result

    result = asyncio.run(verify())
    assert result["n"] == 240
