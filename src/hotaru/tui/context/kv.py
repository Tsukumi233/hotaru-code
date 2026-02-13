"""KV (Key-Value) context for local preferences.

This module provides persistent key-value storage for user preferences
that persist across TUI sessions.
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional, TypeVar, Generic, Callable, List
from contextvars import ContextVar

from ...core.global_paths import GlobalPath
from ...util.log import Log

log = Log.create({"service": "tui.context.kv"})

T = TypeVar("T")


class KVContext:
    """Key-value storage context for preferences.

    Provides persistent storage for user preferences with
    type-safe get/set operations.
    """

    def __init__(self) -> None:
        """Initialize KV context."""
        self._data: Dict[str, Any] = {}
        self._listeners: Dict[str, List[Callable[[Any], None]]] = {}
        self._path = Path(GlobalPath.state()) / "tui_preferences.json"
        self._load()

    def _load(self) -> None:
        """Load preferences from disk."""
        try:
            if self._path.exists():
                with open(self._path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
                log.debug("loaded preferences", {"count": len(self._data)})
        except Exception as e:
            log.warning("failed to load preferences", {"error": str(e)})
            self._data = {}

    def _save(self) -> None:
        """Save preferences to disk."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
        except Exception as e:
            log.warning("failed to save preferences", {"error": str(e)})

    def get(self, key: str, default: T = None) -> T:
        """Get a preference value.

        Args:
            key: Preference key
            default: Default value if not found

        Returns:
            The preference value or default
        """
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a preference value.

        Args:
            key: Preference key
            value: Value to store
        """
        old_value = self._data.get(key)
        self._data[key] = value
        self._save()

        # Notify listeners
        if key in self._listeners:
            for listener in self._listeners[key]:
                try:
                    listener(value)
                except Exception as e:
                    log.error("kv listener error", {"key": key, "error": str(e)})

    def delete(self, key: str) -> None:
        """Delete a preference.

        Args:
            key: Preference key to delete
        """
        if key in self._data:
            del self._data[key]
            self._save()

    def has(self, key: str) -> bool:
        """Check if a preference exists.

        Args:
            key: Preference key

        Returns:
            True if preference exists
        """
        return key in self._data

    def on_change(self, key: str, callback: Callable[[Any], None]) -> Callable[[], None]:
        """Register a callback for preference changes.

        Args:
            key: Preference key to watch
            callback: Function to call when value changes

        Returns:
            Unsubscribe function
        """
        if key not in self._listeners:
            self._listeners[key] = []
        self._listeners[key].append(callback)

        def unsubscribe():
            if key in self._listeners and callback in self._listeners[key]:
                self._listeners[key].remove(callback)

        return unsubscribe

    def toggle(self, key: str, default: bool = False) -> bool:
        """Toggle a boolean preference.

        Args:
            key: Preference key
            default: Default value if not found

        Returns:
            New value after toggle
        """
        current = self.get(key, default)
        new_value = not current
        self.set(key, new_value)
        return new_value


# Context variable
_kv_context: ContextVar[Optional[KVContext]] = ContextVar(
    "kv_context",
    default=None
)


class KVProvider:
    """Provider for KV context."""

    _instance: Optional[KVContext] = None

    @classmethod
    def get(cls) -> KVContext:
        """Get the current KV context."""
        ctx = _kv_context.get()
        if ctx is None:
            ctx = KVContext()
            _kv_context.set(ctx)
            cls._instance = ctx
        return ctx

    @classmethod
    def provide(cls) -> KVContext:
        """Create and provide KV context.

        Returns:
            The KV context
        """
        ctx = KVContext()
        _kv_context.set(ctx)
        cls._instance = ctx
        return ctx

    @classmethod
    def reset(cls) -> None:
        """Reset the KV context."""
        _kv_context.set(None)
        cls._instance = None


def use_kv() -> KVContext:
    """Hook to access KV context."""
    return KVProvider.get()
