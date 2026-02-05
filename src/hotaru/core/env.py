"""Environment variable management.

Provides instance-scoped environment variable access with isolation support.
Note: Full instance isolation will be implemented in Phase 2 when translating
the project/instance module.
"""

import os
from typing import Dict, Optional

# Temporary simplified state - will be replaced with Instance.state in Phase 2
_env_state: Dict[str, str | None] = {}
_initialized = False


def _ensure_initialized():
    """Initialize environment state if not already done."""
    global _initialized, _env_state
    if not _initialized:
        # Create shallow copy to prevent tests from interfering
        _env_state = dict(os.environ)
        _initialized = True


def get(key: str) -> str | None:
    """Get environment variable value.

    Args:
        key: Environment variable name

    Returns:
        Variable value or None if not set
    """
    _ensure_initialized()
    return _env_state.get(key)


def all() -> Dict[str, str | None]:
    """Get all environment variables.

    Returns:
        Dictionary of all environment variables
    """
    _ensure_initialized()
    return _env_state.copy()


def set(key: str, value: str) -> None:
    """Set environment variable.

    Args:
        key: Environment variable name
        value: Value to set
    """
    _ensure_initialized()
    _env_state[key] = value


def remove(key: str) -> None:
    """Remove environment variable.

    Args:
        key: Environment variable name to remove
    """
    _ensure_initialized()
    _env_state.pop(key, None)


class Env:
    """Namespace class for environment variable operations."""

    get = staticmethod(get)
    all = staticmethod(all)
    set = staticmethod(set)
    remove = staticmethod(remove)
