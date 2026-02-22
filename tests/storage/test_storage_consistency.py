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
    return data_dir / "storage"


def _worker(data_home: str, loops: int) -> None:
    os.environ["XDG_DATA_HOME"] = data_home
    Storage.reset()

    async def run() -> None:
        for _ in range(loops):
            await Storage.update(
                ["counter", "shared"],
                lambda d: (
                    time.sleep(0.002),
                    d.__setitem__("n", int(d.get("n", 0)) + 1),
                ),
            )

    asyncio.run(run())


@pytest.mark.anyio
async def test_transaction_put_delete_roundtrip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _setup_storage(monkeypatch, tmp_path)

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


@pytest.mark.anyio
async def test_recover_committed_transaction(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    storage_dir = _setup_storage(monkeypatch, tmp_path)

    tx_dir = storage_dir / "_tx"
    stage_dir = storage_dir / "_tx_stage" / "tx-1"
    tx_dir.mkdir(parents=True, exist_ok=True)
    stage_dir.mkdir(parents=True, exist_ok=True)
    (stage_dir / "doc").mkdir(parents=True, exist_ok=True)
    (stage_dir / "doc" / "a.json").write_text('{"v": 42}', encoding="utf-8")
    (tx_dir / "tx-1.json").write_text(
        json.dumps(
            {
                "id": "tx-1",
                "state": "committed",
                "ops": [
                    {
                        "type": "put",
                        "key": ["doc", "a"],
                        "stage": "tx-1/doc/a.json",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    Storage.reset()
    assert await Storage.read(["doc", "a"]) == {"v": 42}


@pytest.mark.anyio
async def test_initialize_recovers_once_when_called_concurrently(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    storage_dir = _setup_storage(monkeypatch, tmp_path)
    calls: list[Path] = []
    recover = Storage._recover.__func__

    def wrapped(cls, root: Path) -> None:
        calls.append(root)
        time.sleep(0.02)
        recover(cls, root)

    monkeypatch.setattr(Storage, "_recover", classmethod(wrapped))

    paths = await asyncio.gather(*(Storage.initialize() for _ in range(8)))
    assert len(set(paths)) == 1
    assert calls == [storage_dir]


def test_cross_process_update_is_serialized(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    data_home = tmp_path / "xdg"
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    Storage.reset()
    asyncio.run(Storage.write(["counter", "shared"], {"n": 0}))

    ctx = mp.get_context("spawn")
    jobs = [ctx.Process(target=_worker, args=(str(data_home), 60)) for _ in range(4)]
    for job in jobs:
        job.start()
    for job in jobs:
        job.join(timeout=30)
        assert job.exitcode == 0

    result = asyncio.run(Storage.read(["counter", "shared"]))
    assert result["n"] == 240
