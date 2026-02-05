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


class Bus:
    """Event bus for publishing and subscribing to events.

    Provides a simple pub/sub mechanism for decoupled communication
    between components. Supports both synchronous and asynchronous
    callbacks.

    Note: This implementation uses class-level state. In a full
    implementation, subscriptions would be scoped to Instance contexts.
    """

    # Subscriptions by event type
    _subscriptions: Dict[str, List[SubscriptionCallback]] = {}

    @classmethod
    async def publish(cls, event: BusEvent[T], properties: T) -> None:
        """Publish an event to all subscribers.

        Args:
            event: Event definition
            properties: Event properties (must match event's properties_type)

        Raises:
            TypeError: If properties don't match the expected type
        """
        # Validate and convert properties
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

        # Collect all matching subscribers (specific + wildcard)
        callbacks = []
        for key in [event.type, "*"]:
            callbacks.extend(cls._subscriptions.get(key, []))

        # Execute all callbacks
        for callback in callbacks:
            try:
                result = callback(payload)
                if hasattr(result, '__await__'):
                    await result
            except Exception as e:
                _get_log().error("subscription callback failed", {
                    "error": str(e),
                    "type": event.type
                })

    @classmethod
    def subscribe(
        cls,
        event: BusEvent[T],
        callback: Callable[[EventPayload], Union[None, Awaitable[None]]]
    ) -> Callable[[], None]:
        """Subscribe to a specific event type.

        Args:
            event: Event definition to subscribe to
            callback: Function to call when event is published

        Returns:
            Unsubscribe function - call to remove the subscription
        """
        return cls._raw_subscribe(event.type, callback)

    @classmethod
    def subscribe_all(
        cls,
        callback: Callable[[EventPayload], Union[None, Awaitable[None]]]
    ) -> Callable[[], None]:
        """Subscribe to all events.

        Args:
            callback: Function to call for any event

        Returns:
            Unsubscribe function
        """
        return cls._raw_subscribe("*", callback)

    @classmethod
    def once(
        cls,
        event: BusEvent[T],
        callback: Callable[[EventPayload], Union[None, Awaitable[None], bool]]
    ) -> None:
        """Subscribe to an event, auto-unsubscribing after first call.

        The callback can return True or "done" to trigger unsubscription,
        or the subscription will be removed after the first event regardless.

        Args:
            event: Event definition to subscribe to
            callback: Function that may return True/"done" to unsubscribe
        """
        def wrapper(payload: EventPayload):
            result = callback(payload)
            if result == "done" or result is True:
                unsubscribe()

        unsubscribe = cls.subscribe(event, wrapper)

    @classmethod
    def _raw_subscribe(
        cls,
        event_type: str,
        callback: SubscriptionCallback
    ) -> Callable[[], None]:
        """Internal subscription method.

        Args:
            event_type: Event type string or "*" for all events
            callback: Callback function

        Returns:
            Unsubscribe function
        """
        if event_type not in cls._subscriptions:
            cls._subscriptions[event_type] = []

        cls._subscriptions[event_type].append(callback)

        def unsubscribe():
            subs = cls._subscriptions.get(event_type, [])
            if callback in subs:
                subs.remove(callback)

        return unsubscribe

    @classmethod
    def reset(cls) -> None:
        """Reset all subscriptions.

        Useful for testing or when reinitializing the application.
        """
        cls._subscriptions.clear()


# Standard events

class InstanceDisposedProps(BaseModel):
    """Properties for instance.disposed event.

    Attributes:
        directory: Path to the disposed instance directory
    """
    directory: str


# Event fired when an instance is disposed
InstanceDisposed = BusEvent.define("server.instance.disposed", InstanceDisposedProps)
