"""Event bus system for application-wide event publishing and subscription.

Provides a typed event system with support for instance-scoped and global events.
Events are defined with type-safe schemas using Pydantic models.

Example:
    # Define an event
    class UserCreatedProps(BaseModel):
        user_id: str
        email: str

    UserCreated = BusEvent.define("user.created", UserCreatedProps)

    # Subscribe to the event
    def on_user_created(payload):
        print(f"User created: {payload.properties}")

    unsubscribe = Bus.subscribe(UserCreated, on_user_created)

    # Publish the event
    await Bus.publish(UserCreated, UserCreatedProps(user_id="123", email="test@example.com"))

    # Unsubscribe when done
    unsubscribe()
"""

from contextvars import ContextVar, Token
from typing import Any, Callable, Dict, List, TypeVar, Generic, Awaitable, Union, Optional
from pydantic import BaseModel

T = TypeVar('T', bound=BaseModel)

# Lazy logger to avoid circular imports
_log: Optional[Any] = None


def _get_log():
    """Get logger instance lazily to avoid circular imports."""
    global _log
    if _log is None:
        from ..util.log import Log
        _log = Log.create({"service": "bus"})
    return _log


class BusEvent(Generic[T]):
    """Event definition with type and properties schema.

    Each event has a unique type string and a Pydantic model defining
    the structure of its properties.

    Attributes:
        type: Unique event type identifier (e.g., "user.created")
        properties_type: Pydantic model class for event properties
    """

    def __init__(self, event_type: str, properties_type: type[T]):
        """Initialize an event definition.

        Args:
            event_type: Unique event type identifier
            properties_type: Pydantic model class for properties
        """
        self.type = event_type
        self.properties_type = properties_type

    @staticmethod
    def define(event_type: str, properties_type: type[T]) -> 'BusEvent[T]':
        """Define and register a new event type.

        Args:
            event_type: Unique event type identifier (e.g., "user.created")
            properties_type: Pydantic model class for event properties

        Returns:
            BusEvent instance registered in the global registry
        """
        event = BusEvent(event_type, properties_type)
        _registry[event_type] = event
        return event


# Global event registry for introspection
_registry: Dict[str, BusEvent] = {}


class EventPayload(BaseModel):
    """Payload structure delivered to event subscribers.

    Attributes:
        type: Event type identifier
        properties: Event properties as a dictionary
    """
    type: str
    properties: Dict[str, Any]


# Type alias for subscription callbacks
SubscriptionCallback = Callable[[EventPayload], Union[None, Awaitable[None]]]


_bus_var: ContextVar['Bus'] = ContextVar('_bus_var')


class Bus:
    """Event bus for publishing and subscribing to events.

    ContextVar-backed: each AppContext owns a Bus instance.
    Class methods resolve the active instance transparently.
    """

    def __init__(self) -> None:
        self._subscriptions: Dict[str, List[SubscriptionCallback]] = {}

    @classmethod
    def _current(cls) -> 'Bus':
        try:
            return _bus_var.get()
        except LookupError:
            raise RuntimeError("No Bus is bound to the current context")

    @classmethod
    def provide(cls, bus: 'Bus') -> Token['Bus']:
        return _bus_var.set(bus)

    @classmethod
    def restore(cls, token: Token['Bus']) -> None:
        _bus_var.reset(token)

    @classmethod
    async def publish(cls, event: BusEvent[T], properties: T) -> None:
        if not isinstance(properties, event.properties_type):
            if isinstance(properties, dict):
                properties = event.properties_type(**properties)
            else:
                raise TypeError(
                    f"Properties must be instance of {event.properties_type.__name__}"
                )

        payload = EventPayload(
            type=event.type,
            properties=properties.model_dump()
        )

        bus = cls._current()
        callbacks = []
        for key in [event.type, "*"]:
            callbacks.extend(bus._subscriptions.get(key, []))

        for callback in callbacks:
            try:
                result = callback(payload)
                if hasattr(result, '__await__'):
                    await result
            except Exception as e:
                import traceback
                _get_log().error("subscription callback failed", {
                    "error": str(e),
                    "type": event.type,
                    "traceback": traceback.format_exc(),
                })

    @classmethod
    def subscribe(
        cls,
        event: BusEvent[T],
        callback: Callable[[EventPayload], Union[None, Awaitable[None]]]
    ) -> Callable[[], None]:
        return cls._current()._raw_subscribe(event.type, callback)

    @classmethod
    def subscribe_all(
        cls,
        callback: Callable[[EventPayload], Union[None, Awaitable[None]]]
    ) -> Callable[[], None]:
        return cls._current()._raw_subscribe("*", callback)

    @classmethod
    def once(
        cls,
        event: BusEvent[T],
        callback: Callable[[EventPayload], Union[None, Awaitable[None], bool]]
    ) -> None:
        def wrapper(payload: EventPayload):
            result = callback(payload)
            if result == "done" or result is True:
                unsubscribe()

        unsubscribe = cls.subscribe(event, wrapper)

    def _raw_subscribe(
        self,
        event_type: str,
        callback: SubscriptionCallback,
    ) -> Callable[[], None]:
        if event_type not in self._subscriptions:
            self._subscriptions[event_type] = []

        self._subscriptions[event_type].append(callback)

        def unsubscribe() -> None:
            subs = self._subscriptions.get(event_type, [])
            if callback in subs:
                subs.remove(callback)

        return unsubscribe

    def clear(self) -> None:
        self._subscriptions.clear()

    @classmethod
    def reset(cls) -> None:
        try:
            cls._current().clear()
        except RuntimeError:
            pass


# Standard events

class InstanceDisposedProps(BaseModel):
    """Properties for instance.disposed event.

    Attributes:
        directory: Path to the disposed instance directory
    """
    directory: str


# Event fired when an instance is disposed
InstanceDisposed = BusEvent.define("server.instance.disposed", InstanceDisposedProps)
