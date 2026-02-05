"""Event bus system for application-wide event publishing and subscription.

Provides a typed event system with support for instance-scoped and global events.
Events are defined with type-safe schemas using Pydantic models.
"""

from typing import Any, Callable, Dict, List, TypeVar, Generic, Awaitable, Union
from pydantic import BaseModel

from ..util.log import Log

log = Log.create({"service": "bus"})

T = TypeVar('T', bound=BaseModel)


class BusEvent(Generic[T]):
    """Event definition with type and properties schema.

    Example:
        UserCreated = BusEvent(
            event_type="user.created",
            properties_type=UserCreatedProps
        )
    """

    def __init__(self, event_type: str, properties_type: type[T]):
        self.type = event_type
        self.properties_type = properties_type

    @staticmethod
    def define(event_type: str, properties_type: type[T]) -> 'BusEvent[T]':
        """Define a new event type.

        Args:
            event_type: Unique event type identifier (e.g., "user.created")
            properties_type: Pydantic model class for event properties

        Returns:
            BusEvent instance
        """
        event = BusEvent(event_type, properties_type)
        _registry[event_type] = event
        return event


# Global event registry
_registry: Dict[str, BusEvent] = {}


class EventPayload(BaseModel):
    """Base event payload structure."""
    type: str
    properties: Dict[str, Any]


# Subscription callback type
SubscriptionCallback = Callable[[EventPayload], Union[None, Awaitable[None]]]


class Bus:
    """Event bus for publishing and subscribing to events.

    Note: This is a simplified version that doesn't yet integrate with
    Instance.state() from the project module. That integration will come
    in Phase 2 when we translate the project/instance module.
    """

    # Instance-scoped subscriptions (will be replaced with Instance.state in Phase 2)
    _subscriptions: Dict[str, List[SubscriptionCallback]] = {}

    @classmethod
    async def publish(cls, event: BusEvent[T], properties: T) -> None:
        """Publish an event to all subscribers.

        Args:
            event: Event definition
            properties: Event properties (must match event's properties_type)
        """
        # Validate properties match schema
        if not isinstance(properties, event.properties_type):
            # Convert dict to model if needed
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

        log.info("publishing", {"type": event.type})

        # Collect all matching subscribers
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
                log.error("subscription callback failed", {"error": e, "type": event.type})

    @classmethod
    def subscribe(
        cls,
        event: BusEvent[T],
        callback: Callable[[EventPayload], Union[None, Awaitable[None]]]
    ) -> Callable[[], None]:
        """Subscribe to an event.

        Args:
            event: Event definition to subscribe to
            callback: Function to call when event is published

        Returns:
            Unsubscribe function
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
        """Subscribe to an event, auto-unsubscribing after first matching event.

        Args:
            event: Event definition to subscribe to
            callback: Function returning True/"done" to unsubscribe
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
        log.info("subscribing", {"type": event_type})

        if event_type not in cls._subscriptions:
            cls._subscriptions[event_type] = []

        cls._subscriptions[event_type].append(callback)

        def unsubscribe():
            log.info("unsubscribing", {"type": event_type})
            subs = cls._subscriptions.get(event_type, [])
            if callback in subs:
                subs.remove(callback)

        return unsubscribe


# Standard events (will be expanded in Phase 2)
class InstanceDisposedProps(BaseModel):
    """Properties for instance.disposed event."""
    directory: str


InstanceDisposed = BusEvent.define("server.instance.disposed", InstanceDisposedProps)
