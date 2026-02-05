"""Async context management using contextvars.

Provides a pattern similar to AsyncLocalStorage in Node.js, allowing
context to be propagated through async call chains without explicit passing.
"""

from contextvars import ContextVar
from typing import TypeVar, Generic, Callable, Any

T = TypeVar('T')


class ContextNotFoundError(Exception):
    """Raised when attempting to access context that hasn't been provided."""

    def __init__(self, name: str):
        self.name = name
        super().__init__(f"No context found for {name}")


class Context(Generic[T]):
    """Context container for async-safe state propagation.

    Example:
        user_context = Context.create("user")

        async def handler():
            user = user_context.use()
            print(user)

        async def main():
            await user_context.provide({"id": 123}, handler)
    """

    def __init__(self, name: str, storage: ContextVar[T]):
        self.name = name
        self._storage = storage

    def use(self) -> T:
        """Get the current context value.

        Raises:
            ContextNotFoundError: If no context has been provided
        """
        result = self._storage.get(None)
        if result is None:
            raise ContextNotFoundError(self.name)
        return result

    async def provide(self, value: T, fn: Callable[[], Any]) -> Any:
        """Provide context value for the duration of fn execution.

        Args:
            value: Context value to provide
            fn: Async or sync function to execute with context

        Returns:
            Result of fn
        """
        token = self._storage.set(value)
        try:
            result = fn()
            # Handle both sync and async functions
            if hasattr(result, '__await__'):
                return await result
            return result
        finally:
            self._storage.reset(token)

    @staticmethod
    def create(name: str) -> 'Context[T]':
        """Create a new context container.

        Args:
            name: Descriptive name for error messages

        Returns:
            New Context instance
        """
        storage: ContextVar[T] = ContextVar(name)
        return Context(name=name, storage=storage)
