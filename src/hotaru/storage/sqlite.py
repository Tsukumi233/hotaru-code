"""SQLite storage backend with WAL mode.

Replaces the hierarchical JSON file storage with a single SQLite database.
Uses synchronous sqlite3 — local-disk I/O is sub-millisecond and does not
justify an extra background thread (mirrors opencode's approach).
"""

import asyncio
import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal, Optional, Sequence

from ..core.global_paths import GlobalPath
from ..util.log import Log

log = Log.create({"service": "storage"})


class NotFoundError(Exception):
    """Raised when a storage resource is not found."""

    def __init__(self, key: list[str]):
        self.key = key
        super().__init__(f"Resource not found: {'/'.join(key)}")


class TxOp:
    """Single storage transaction operation."""

    __slots__ = ("type", "key", "content")

    def __init__(self, type: Literal["put", "delete"], key: list[str], content: Any = None):
        self.type = type
        self.key = key
        self.content = content


# ---------------------------------------------------------------------------
# Key encoding: list[str] → single TEXT column
# ---------------------------------------------------------------------------

def _encode_key(key: list[str]) -> str:
    return "/".join(key)


def _decode_key(encoded: str) -> list[str]:
    return encoded.split("/")


# ---------------------------------------------------------------------------
# Namespace routing: first segment of key → table name
# ---------------------------------------------------------------------------

_TABLE_MAP = {
    "session": "sessions",
    "session_index": "session_index",
    "message_store": "messages",
    "part": "parts",
    "permission_approval": "permission_approval",
}

_PLACEHOLDER_CONTENT = "PLACEHOLDER_FOR_APPEND"


def _table(key: list[str]) -> str:
    if not key:
        return "kv"
    return _TABLE_MAP.get(key[0], "kv")


_TABLES = ("sessions", "session_index", "messages", "parts", "permission_approval", "kv")


class Storage:
    """SQLite-backed storage with WAL mode.

    Drop-in replacement for the JSON file storage.
    All data lives in ``<data_dir>/storage.db``.
    """

    _db: Optional[sqlite3.Connection] = None
    _ready = False
    _lock = threading.Lock()
    _path: Optional[str] = None

    @classmethod
    async def initialize(cls) -> str:
        return cls._init()

    @classmethod
    def _init(cls) -> str:
        if cls._ready and cls._db is not None:
            return cls._path
        with cls._lock:
            if cls._ready and cls._db is not None:
                return cls._path
            data = GlobalPath.data()
            Path(data).mkdir(parents=True, exist_ok=True)
            cls._path = str(Path(data) / "storage.db")
            cls._db = sqlite3.connect(cls._path)
            cls._db.execute("PRAGMA journal_mode=WAL")
            cls._db.execute("PRAGMA synchronous=NORMAL")
            cls._db.execute("PRAGMA busy_timeout=5000")
            for table in _TABLES:
                cls._db.execute(f"""
                    CREATE TABLE IF NOT EXISTS {table} (
                        key TEXT PRIMARY KEY,
                        data TEXT NOT NULL
                    )
                """)
            cls._db.commit()
            cls._migrate_json(data)
            cls._ready = True
            return cls._path

    @classmethod
    def _conn(cls) -> sqlite3.Connection:
        if cls._db is None:
            cls._init()
        return cls._db

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    @classmethod
    def put(cls, key: list[str], content: Any) -> TxOp:
        return TxOp(type="put", key=key, content=content)

    @classmethod
    def delete(cls, key: list[str]) -> TxOp:
        return TxOp(type="delete", key=key)

    @classmethod
    async def read(cls, key: list[str]) -> Any:
        db = cls._conn()
        row = db.execute(
            f"SELECT data FROM {_table(key)} WHERE key = ?",
            (_encode_key(key),),
        ).fetchone()
        if row is None:
            raise NotFoundError(key)
        return json.loads(row[0])

    @classmethod
    async def write(cls, key: list[str], content: Any) -> None:
        db = cls._conn()
        db.execute(
            f"INSERT OR REPLACE INTO {_table(key)} (key, data) VALUES (?, ?)",
            (_encode_key(key), json.dumps(content, ensure_ascii=False)),
        )
        db.commit()

    @classmethod
    async def update(cls, key: list[str], fn: Callable[[Any], None]) -> Any:
        db = cls._conn()
        encoded = _encode_key(key)
        table = _table(key)
        db.execute("BEGIN IMMEDIATE")
        try:
            row = db.execute(
                f"SELECT data FROM {table} WHERE key = ?", (encoded,)
            ).fetchone()
            if row is None:
                db.execute("ROLLBACK")
                raise NotFoundError(key)
            data = json.loads(row[0])
            fn(data)
            db.execute(
                f"INSERT OR REPLACE INTO {table} (key, data) VALUES (?, ?)",
                (encoded, json.dumps(data, ensure_ascii=False)),
            )
            db.execute("COMMIT")
        except NotFoundError:
            raise
        except Exception:
            db.execute("ROLLBACK")
            raise
        return data

    @classmethod
    async def remove(cls, key: list[str]) -> None:
        db = cls._conn()
        db.execute(f"DELETE FROM {_table(key)} WHERE key = ?", (_encode_key(key),))
        db.commit()

    @classmethod
    async def transaction(
        cls,
        ops: list[TxOp],
        effects: Optional[Sequence[Callable[[], Awaitable[None]]]] = None,
    ) -> None:
        if not ops:
            return
        db = cls._conn()
        for op in ops:
            encoded = _encode_key(op.key)
            table = _table(op.key)
            if op.type == "put":
                db.execute(
                    f"INSERT OR REPLACE INTO {table} (key, data) VALUES (?, ?)",
                    (encoded, json.dumps(op.content, ensure_ascii=False)),
                )
            elif op.type == "delete":
                db.execute(f"DELETE FROM {table} WHERE key = ?", (encoded,))
        db.commit()
        if effects:
            for effect in effects:
                try:
                    await effect()
                except Exception as exc:
                    log.warn("transaction effect failed", {"error": str(exc)})

    @classmethod
    async def list(cls, prefix: list[str]) -> list[list[str]]:
        db = cls._conn()
        encoded = _encode_key(prefix)
        table = _table(prefix)
        rows = db.execute(
            f"SELECT key FROM {table} WHERE key LIKE ? ORDER BY key",
            (encoded + "/%",),
        ).fetchall()
        return [_decode_key(row[0]) for row in rows]

    # ------------------------------------------------------------------
    # JSON migration
    # ------------------------------------------------------------------

    @classmethod
    def _migrate_json(cls, data_dir: str) -> None:
        json_dir = Path(data_dir) / "storage"
        if not json_dir.is_dir():
            return
        marker = json_dir / ".migrated"
        if marker.exists():
            return
        count = 0
        for root, _dirs, files in os.walk(json_dir):
            for file in files:
                if not file.endswith(".json"):
                    continue
                full = os.path.join(root, file)
                rel = os.path.relpath(full, str(json_dir))
                key = rel[:-5].replace("\\", "/").split("/")
                if key and key[0] in ("_tx", "_tx_stage"):
                    continue
                try:
                    with open(full, "r", encoding="utf-8") as f:
                        content = json.load(f)
                except Exception:
                    continue
                cls._db.execute(
                    f"INSERT OR IGNORE INTO {_table(key)} (key, data) VALUES (?, ?)",
                    (_encode_key(key), json.dumps(content, ensure_ascii=False)),
                )
                count += 1
        if count > 0:
            cls._db.commit()
            log.info("migrated JSON storage to SQLite", {"count": count})
        marker.touch()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @classmethod
    def close(cls) -> None:
        """Close the database connection."""
        if cls._db is not None:
            try:
                cls._db.close()
            except Exception:
                pass
            cls._db = None
            cls._ready = False

    @classmethod
    def reset(cls) -> None:
        """Close and reset all class-level state."""
        cls.close()
        cls._lock = threading.Lock()
        cls._path = None
