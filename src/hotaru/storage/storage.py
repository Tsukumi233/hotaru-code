"""Hierarchical JSON file storage.

Provides a file-based storage layer following OpenCode's Storage pattern.
Keys like ["session", projectID, sessionID] map to
``storage/session/{projectID}/{sessionID}.json``.
"""

import json
import os
import shutil
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Optional, TypeVar

from ..core.global_paths import GlobalPath
from ..util.log import Log
from .lock import Lock

log = Log.create({"service": "storage"})

T = TypeVar("T")


@dataclass(frozen=True)
class TxOp:
    """Single JSON storage transaction operation."""

    type: Literal["put", "delete"]
    key: list[str]
    content: Any = None


class NotFoundError(Exception):
    """Raised when a storage resource is not found."""

    def __init__(self, key: list[str]):
        self.key = key
        super().__init__(f"Resource not found: {'/'.join(key)}")


class Storage:
    """Hierarchical JSON file storage.

    All data is stored as ``.json`` files under ``<data_dir>/storage/``.
    Concurrent access is protected by reader-writer locks.
    """

    _dir: Optional[str] = None
    _ready = False
    _guard = threading.Lock()
    _durable = {"session", "message_store", "part"}

    @classmethod
    def _get_dir(cls) -> str:
        with cls._guard:
            if cls._dir is None:
                cls._dir = str(Path(GlobalPath.data()) / "storage")
                Path(cls._dir).mkdir(parents=True, exist_ok=True)
            if not cls._ready:
                cls._recover(Path(cls._dir))
                cls._ready = True
            return cls._dir

    @classmethod
    def _key_to_path(cls, key: list[str]) -> str:
        return os.path.join(cls._get_dir(), *key) + ".json"

    @classmethod
    def _key_to_file(cls, key: list[str]) -> Path:
        return Path(cls._key_to_path(key))

    @classmethod
    def _durable_key(cls, key: list[str]) -> bool:
        return bool(key) and key[0] in cls._durable

    @classmethod
    def _json_bytes(cls, content: Any) -> bytes:
        return json.dumps(content, indent=2, ensure_ascii=False).encode("utf-8")

    @classmethod
    def _fsync_dir(cls, parent: Path) -> None:
        try:
            fd = os.open(parent, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    @classmethod
    def _write_bytes(cls, target: Path, body: bytes, *, durable: bool) -> None:
        parent = target.parent
        parent.mkdir(parents=True, exist_ok=True)
        tmp = parent / f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        try:
            with open(tmp, "wb") as file:
                file.write(body)
                file.flush()
                if durable:
                    os.fsync(file.fileno())
            os.replace(tmp, target)
            if durable:
                cls._fsync_dir(parent)
        finally:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass

    @classmethod
    def _write_json(cls, target: Path, content: Any, *, durable: bool) -> None:
        cls._write_bytes(target, cls._json_bytes(content), durable=durable)

    @classmethod
    def put(cls, key: list[str], content: Any) -> TxOp:
        """Build a put operation for ``Storage.transaction``."""
        return TxOp(type="put", key=key, content=content)

    @classmethod
    def delete(cls, key: list[str]) -> TxOp:
        """Build a delete operation for ``Storage.transaction``."""
        return TxOp(type="delete", key=key)

    @classmethod
    def _tx_file(cls, root: Path, txid: str) -> Path:
        return root / "_tx" / f"{txid}.json"

    @classmethod
    def _tx_stage(cls, root: Path, stage: str) -> Path:
        return root / "_tx_stage" / stage

    @classmethod
    def _tx_write(cls, root: Path, record: dict[str, Any]) -> None:
        txid = str(record.get("id", "tx"))
        cls._write_json(cls._tx_file(root, txid), record, durable=True)

    @classmethod
    def _apply(cls, root: Path, record: dict[str, Any]) -> None:
        for raw in record.get("ops", []):
            kind = raw.get("type")
            key = raw.get("key")
            if not isinstance(key, list) or not all(isinstance(v, str) for v in key):
                continue

            target = Path(str(root.joinpath(*key)) + ".json")
            if kind == "put":
                stage = raw.get("stage")
                if not isinstance(stage, str):
                    continue
                source = cls._tx_stage(root, stage)
                if not source.exists():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(source, target)
                if cls._durable_key(key):
                    cls._fsync_dir(target.parent)
                continue

            if kind == "delete":
                try:
                    os.unlink(target)
                except FileNotFoundError:
                    pass
                if cls._durable_key(key):
                    cls._fsync_dir(target.parent)

    @classmethod
    def _cleanup_tx(cls, root: Path, txid: str) -> None:
        try:
            os.unlink(cls._tx_file(root, txid))
        except FileNotFoundError:
            pass
        shutil.rmtree(root / "_tx_stage" / txid, ignore_errors=True)

    @classmethod
    def _recover(cls, root: Path) -> None:
        tx_dir = root / "_tx"
        if not tx_dir.is_dir():
            return
        files = sorted(tx_dir.glob("*.json"))
        for file in files:
            try:
                record = json.loads(file.read_text(encoding="utf-8"))
            except Exception:
                continue
            txid = str(record.get("id") or file.stem)
            state = str(record.get("state", "")).lower()

            if state == "committed":
                cls._apply(root, record)
                record["id"] = txid
                record["state"] = "applied"
                cls._tx_write(root, record)
                cls._cleanup_tx(root, txid)
                continue

            if state in {"prepared", "applied"}:
                cls._cleanup_tx(root, txid)

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    @classmethod
    async def read(cls, key: list[str]) -> Any:
        """Read a JSON resource.

        Args:
            key: Hierarchical key, e.g. ``["session", project_id, session_id]``

        Returns:
            Parsed JSON data.

        Raises:
            NotFoundError: If the resource does not exist.
        """
        target = cls._key_to_path(key)
        async with Lock.read(target):
            try:
                with open(target, "r", encoding="utf-8") as file:
                    return json.load(file)
            except FileNotFoundError:
                raise NotFoundError(key)

    @classmethod
    async def write(cls, key: list[str], content: Any) -> None:
        """Write a JSON resource (creates parent dirs as needed).

        Args:
            key: Hierarchical key.
            content: Data to serialise as JSON.
        """
        target = cls._key_to_path(key)
        async with Lock.write(target):
            cls._write_json(cls._key_to_file(key), content, durable=cls._durable_key(key))

    @classmethod
    async def update(
        cls,
        key: list[str],
        fn: Callable[[Any], None],
    ) -> Any:
        """Read-modify-write a JSON resource under an exclusive lock.

        Args:
            key: Hierarchical key.
            fn: Mutator that receives the parsed dict and modifies it in place.

        Returns:
            The modified data.

        Raises:
            NotFoundError: If the resource does not exist.
        """
        target = cls._key_to_path(key)
        async with Lock.write(target):
            try:
                with open(target, "r", encoding="utf-8") as file:
                    data = json.load(file)
            except FileNotFoundError:
                raise NotFoundError(key)

            fn(data)
            cls._write_json(cls._key_to_file(key), data, durable=cls._durable_key(key))
            return data

    @classmethod
    async def remove(cls, key: list[str]) -> None:
        """Delete a resource (no error if missing).

        Args:
            key: Hierarchical key.
        """
        target = cls._key_to_path(key)
        async with Lock.write(target):
            try:
                os.unlink(target)
            except FileNotFoundError:
                pass
            if cls._durable_key(key):
                cls._fsync_dir(Path(target).parent)

    @classmethod
    async def transaction(cls, ops: list[TxOp]) -> None:
        """Atomically apply multiple storage operations."""
        if not ops:
            return

        root = Path(cls._get_dir())
        targets = [cls._key_to_path(op.key) for op in ops]
        txid = f"tx-{uuid.uuid4().hex}"
        record: dict[str, Any] = {"id": txid, "state": "prepared", "ops": []}

        async with Lock.write_many(targets):
            for op in ops:
                if op.type == "delete":
                    record["ops"].append({"type": "delete", "key": op.key})
                    continue

                stage = str(Path(txid).joinpath(*op.key)) + ".json"
                cls._write_json(cls._tx_stage(root, stage), op.content, durable=True)
                record["ops"].append({"type": "put", "key": op.key, "stage": stage})

            cls._tx_write(root, record)
            record["state"] = "committed"
            cls._tx_write(root, record)

            cls._apply(root, record)
            record["state"] = "applied"
            cls._tx_write(root, record)
            cls._cleanup_tx(root, txid)

    @classmethod
    async def list(cls, prefix: list[str]) -> list[list[str]]:
        """List all resources under a prefix.

        Args:
            prefix: Key prefix, e.g. ``["session", project_id]``.

        Returns:
            Sorted list of full keys (each key is a list of strings).
        """
        base = os.path.join(cls._get_dir(), *prefix)
        result: list[list[str]] = []

        if not os.path.isdir(base):
            return result

        for root, _dirs, files in os.walk(base):
            for file in files:
                if not file.endswith(".json"):
                    continue
                full = os.path.join(root, file)
                rel = os.path.relpath(full, cls._get_dir())
                key = rel[:-5].replace("\\", "/").split("/")
                result.append(key)

        result.sort()
        return result

    @classmethod
    def reset(cls) -> None:
        """Reset cached directory (for testing)."""
        cls._dir = None
        cls._ready = False
