"""TUI context providers for state management.

This module provides context-based state management for the TUI,
similar to React/Solid.js context patterns but using Python's
contextvars and class-based state management.
"""

from .route import RouteContext, RouteProvider, Route, HomeRoute, SessionRoute, use_route
from .local import LocalContext, LocalProvider, use_local
from .sync import SyncContext, SyncProvider, use_sync
from .args import ArgsContext, ArgsProvider, Args, use_args
from .kv import KVContext, KVProvider, use_kv
from .sdk import SDKContext, SDKProvider, use_sdk

__all__ = [
    # Route
    "RouteContext",
    "RouteProvider",
    "Route",
    "HomeRoute",
    "SessionRoute",
    "use_route",
    # Local
    "LocalContext",
    "LocalProvider",
    "use_local",
    # Sync
    "SyncContext",
    "SyncProvider",
    "use_sync",
    # Args
    "ArgsContext",
    "ArgsProvider",
    "Args",
    "use_args",
    # KV
    "KVContext",
    "KVProvider",
    "use_kv",
    # SDK
    "SDKContext",
    "SDKProvider",
    "use_sdk",
]
