"""Subscription lifecycle helper for TUI screens/widgets."""

from __future__ import annotations

from typing import Callable, List


class ScreenSubscriptions:
    """Track and release unsubscribe callbacks as a unit."""

    def __init__(self) -> None:
        self._unsubscribers: List[Callable[[], None]] = []

    def add(self, unsubscribe: Callable[[], None]) -> None:
        self._unsubscribers.append(unsubscribe)

    def clear(self) -> None:
        while self._unsubscribers:
            unsubscribe = self._unsubscribers.pop()
            try:
                unsubscribe()
            except Exception:
                # Listener disposal should not crash unmount flow.
                continue
