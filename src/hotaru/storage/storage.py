"""Hierarchical JSON file storage.

Provides a file-based storage layer following OpenCode's Storage pattern.
Keys like ["session", projectID, sessionID] map to
``storage/session/{projectID}/{sessionID}.json``.
"""

import json
import os
from pathlib import Path
from typing import Any, Callable, List, Optional, TypeVar

from ..core.global_paths import GlobalPath
from ..util.log import Log
from .lock import Lock

log = Log.create({"service": "storage"})

T = TypeVar("T")


class NotFoundError(Exception):
    """Raised when a storage resource is not found."""

    def __init__(self, key: List[str]):
        self.key = key
        super().__init__(f"Resource not found: {'/'.join(key)}")


class Storage:
    """Hierarchical JSON file storage.

    All data is stored as ``.json`` files under ``<data_dir>/storage/``.
    Concurrent access is protected by async reader-writer locks.
    """

    _dir: Optional[str] = None

    @classmethod
    def _get_dir(cls) -> str:
        if cls._dir is None:
            cls._dir = str(Path(GlobalPath.data) / "storage")
            Path(cls._dir).mkdir(parents=True, exist_ok=True)
        return cls._dir

    @classmethod
    def _key_to_path(cls, key: List[str]) -> str:
        return os.path.join(cls._get_dir(), *key) + ".json"

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    @classmethod
    async def read(cls, key: List[str]) -> Any:
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
                with open(target, "r", encoding="utf-8") as f:
                    return json.load(f)
            except FileNotFoundError:
                raise NotFoundError(key)

    @classmethod
    async def write(cls, key: List[str], content: Any) -> None:
        """Write a JSON resource (creates parent dirs as needed).

        Args:
            key: Hierarchical key.
            content: Data to serialise as JSON.
        """
        target = cls._key_to_path(key)
        async with Lock.write(target):
            Path(target).parent.mkdir(parents=True, exist_ok=True)
            with open(target, "w", encoding="utf-8") as f:
                json.dump(content, f, indent=2, ensure_ascii=False)

    @classmethod
    async def update(
        cls,
        key: List[str],
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
                with open(target, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except FileNotFoundError:
                raise NotFoundError(key)

            fn(data)

            with open(target, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            return data

    @classmethod
    async def remove(cls, key: List[str]) -> None:
        """Delete a resource (no error if missing).

        Args:
            key: Hierarchical key.
        """
        target = cls._key_to_path(key)
        try:
            os.unlink(target)
        except FileNotFoundError:
            pass

    @classmethod
    async def list(cls, prefix: List[str]) -> List[List[str]]:
        """List all resources under a prefix.

        Args:
            prefix: Key prefix, e.g. ``["session", project_id]``.

        Returns:
            Sorted list of full keys (each key is a list of strings).
        """
        base = os.path.join(cls._get_dir(), *prefix)
        results: List[List[str]] = []

        if not os.path.isdir(base):
            return results

        for root, _dirs, files in os.walk(base):
            for fname in files:
                if not fname.endswith(".json"):
                    continue
                full = os.path.join(root, fname)
                rel = os.path.relpath(full, cls._get_dir())
                # Strip .json and split into key parts
                rel_no_ext = rel[:-5]  # remove ".json"
                parts = rel_no_ext.replace("\\", "/").split("/")
                results.append(parts)

        results.sort()
        return results

    @classmethod
    def reset(cls) -> None:
        """Reset cached directory (for testing)."""
        cls._dir = None
