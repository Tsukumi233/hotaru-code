"""Route context for TUI navigation.

This module provides routing state management for navigating
between different screens in the TUI.
"""

from dataclasses import dataclass, field
from typing import Optional, Union, Callable, List, Any
from contextvars import ContextVar

from ...util.log import Log

log = Log.create({"service": "tui.context.route"})


@dataclass
class PromptInfo:
    """Information about a prompt input state.

    Attributes:
        input: The text input content
        parts: Additional parts (files, etc.)
    """
    input: str = ""
    parts: List[Any] = field(default_factory=list)


@dataclass
class HomeRoute:
    """Home screen route.

    Attributes:
        type: Route type identifier
        initial_prompt: Optional initial prompt to populate
    """
    type: str = "home"
    initial_prompt: Optional[PromptInfo] = None


@dataclass
class SessionRoute:
    """Session screen route.

    Attributes:
        type: Route type identifier
        session_id: ID of the session to display
        initial_prompt: Optional initial prompt to populate
    """
    type: str = "session"
    session_id: str = ""
    initial_prompt: Optional[PromptInfo] = None


# Union type for all routes
Route = Union[HomeRoute, SessionRoute]


class RouteContext:
    """Route context for managing navigation state.

    Provides methods for navigating between screens and
    accessing the current route data.
    """

    def __init__(self) -> None:
        """Initialize route context with home route."""
        self._route: Route = HomeRoute()
        self._listeners: List[Callable[[Route], None]] = []

    @property
    def data(self) -> Route:
        """Get the current route data."""
        return self._route

    def navigate(self, route: Route) -> None:
        """Navigate to a new route.

        Args:
            route: The route to navigate to
        """
        log.debug("navigating", {"route_type": route.type})
        self._route = route

        # Notify listeners
        for listener in self._listeners:
            try:
                listener(route)
            except Exception as e:
                log.error("route listener error", {"error": str(e)})

    def on_change(self, callback: Callable[[Route], None]) -> Callable[[], None]:
        """Register a callback for route changes.

        Args:
            callback: Function to call when route changes

        Returns:
            Unsubscribe function
        """
        self._listeners.append(callback)

        def unsubscribe():
            if callback in self._listeners:
                self._listeners.remove(callback)

        return unsubscribe

    def is_home(self) -> bool:
        """Check if current route is home."""
        return self._route.type == "home"

    def is_session(self) -> bool:
        """Check if current route is session."""
        return self._route.type == "session"

    def get_session_id(self) -> Optional[str]:
        """Get current session ID if on session route."""
        if isinstance(self._route, SessionRoute):
            return self._route.session_id
        return None


# Context variable for route context
_route_context: ContextVar[Optional[RouteContext]] = ContextVar(
    "route_context",
    default=None
)


class RouteProvider:
    """Provider for route context.

    Manages the lifecycle of the route context and provides
    access to it throughout the application.
    """

    _instance: Optional[RouteContext] = None

    @classmethod
    def get(cls) -> RouteContext:
        """Get the current route context.

        Returns:
            The route context instance

        Raises:
            RuntimeError: If no route context is available
        """
        ctx = _route_context.get()
        if ctx is None:
            # Create default context if none exists
            ctx = RouteContext()
            _route_context.set(ctx)
        return ctx

    @classmethod
    def provide(cls, initial_route: Optional[Route] = None) -> RouteContext:
        """Create and provide a new route context.

        Args:
            initial_route: Optional initial route

        Returns:
            The new route context
        """
        ctx = RouteContext()
        if initial_route:
            ctx._route = initial_route
        _route_context.set(ctx)
        cls._instance = ctx
        return ctx

    @classmethod
    def reset(cls) -> None:
        """Reset the route context."""
        _route_context.set(None)
        cls._instance = None


def use_route() -> RouteContext:
    """Hook to access the route context.

    Returns:
        The current route context
    """
    return RouteProvider.get()
