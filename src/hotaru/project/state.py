"""Instance-scoped state management.

Provides lazy initialization and automatic disposal of state tied to instance lifecycle.
"""

import asyncio
from typing import Any, Awaitable, Callable, Dict, Generic, TypeVar

from ..util.log import Log

log = Log.create({"service": "state"})

S = TypeVar('S')


class StateEntry(Generic[S]):
    """Container for state with optional disposal function."""

    def __init__(
        self,
        state: S,
        dispose: Callable[[S], Awaitable[None]] | None = None
    ):
        self.state = state
        self.dispose = dispose


class State:
    """Namespace for instance-scoped state management.

    State is lazily initialized on first access and automatically disposed
    when the owning instance is disposed.

    Example:
        # Define state factory
        def create_connection():
            return DatabaseConnection()

        # Create state accessor
        get_connection = State.create(
            lambda: Instance.directory(),
            create_connection,
            lambda conn: conn.close()
        )

        # Use in instance context
        conn = get_connection()
    """

    _records_by_key: Dict[str, Dict[Any, StateEntry]] = {}

    @classmethod
    def create(
        cls,
        root: Callable[[], str],
        init: Callable[[], S],
        dispose: Callable[[S], Awaitable[None]] | None = None
    ) -> Callable[[], S]:
        """Create a state accessor function.

        Args:
            root: Function returning the state key (typically Instance.directory())
            init: Factory function to create the state
            dispose: Optional async function to clean up the state

        Returns:
            Function that returns the state, creating it if necessary
        """
        def accessor() -> S:
            key = root()

            if key not in cls._records_by_key:
                cls._records_by_key[key] = {}

            entries = cls._records_by_key[key]

            # Use init function as the unique identifier
            if init in entries:
                return entries[init].state

            # Create new state
            state = init()
            entries[init] = StateEntry(state=state, dispose=dispose)
            return state

        return accessor

    @classmethod
    async def dispose(cls, key: str) -> None:
        """Dispose all state for a given key.

        Args:
            key: The state key (typically Instance.directory())
        """
        entries = cls._records_by_key.get(key)
        if not entries:
            return

        log.info("waiting for state disposal to complete", {"key": key})

        disposal_finished = False

        async def timeout_warning():
            await asyncio.sleep(10)
            if not disposal_finished:
                log.warn(
                    "state disposal is taking an unusually long time - "
                    "if it does not complete in a reasonable time, please report this as a bug",
                    {"key": key}
                )

        # Start timeout warning task
        warning_task = asyncio.create_task(timeout_warning())

        try:
            tasks = []
            for init_fn, entry in entries.items():
                if not entry.dispose:
                    continue

                label = getattr(init_fn, '__name__', str(init_fn))

                async def dispose_entry(e: StateEntry, lbl: str):
                    try:
                        state = e.state
                        # Handle if state is a coroutine/awaitable
                        if asyncio.iscoroutine(state) or asyncio.isfuture(state):
                            state = await state
                        await e.dispose(state)
                    except Exception as error:
                        log.error("Error while disposing state:", {"error": error, "key": key, "init": lbl})

                tasks.append(dispose_entry(entry, label))

            await asyncio.gather(*tasks)

            entries.clear()
            del cls._records_by_key[key]

            disposal_finished = True
            log.info("state disposal completed", {"key": key})
        finally:
            warning_task.cancel()
            try:
                await warning_task
            except asyncio.CancelledError:
                pass
