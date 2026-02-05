"""Monotonic ID generation with prefixes.

Generates sortable, unique identifiers with type prefixes similar to Stripe IDs.
IDs are monotonically increasing (or decreasing) and embed timestamp information.
"""

import secrets
import time
from typing import Literal

# ID prefixes for different entity types
PREFIX_MAP = {
    "session": "ses",
    "message": "msg",
    "permission": "per",
    "question": "que",
    "user": "usr",
    "part": "prt",
    "pty": "pty",
    "tool": "tool",
    "call": "call",
}

IDPrefix = Literal["session", "message", "permission", "question", "user", "part", "pty", "tool", "call"]

LENGTH = 26

# State for monotonic ID generation
_last_timestamp = 0
_counter = 0


def _random_base62(length: int) -> str:
    """Generate a random base62 string of specified length."""
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    return ''.join(secrets.choice(chars) for _ in range(length))


def _create(prefix: IDPrefix, descending: bool, timestamp: float | None = None) -> str:
    """Create a new ID with the given prefix and ordering.

    Args:
        prefix: Entity type prefix
        descending: If True, newer IDs sort before older ones
        timestamp: Optional timestamp (for testing), defaults to current time

    Returns:
        Formatted ID string like "ses_0123456789abcdefghijklmnop"
    """
    global _last_timestamp, _counter

    current_timestamp = timestamp if timestamp is not None else int(time.time() * 1000)

    # Monotonic counter: increment if same millisecond
    if current_timestamp != _last_timestamp:
        _last_timestamp = current_timestamp
        _counter = 0
    _counter += 1

    # Encode timestamp + counter into 48 bits
    now = (current_timestamp * 0x1000) + _counter

    # Invert bits for descending order
    if descending:
        now = ~now & 0xFFFFFFFFFFFF  # Mask to 48 bits

    # Convert to hex (12 characters for 48 bits)
    time_hex = format(now, '012x')

    # Add random suffix
    random_suffix = _random_base62(LENGTH - 12)

    return f"{PREFIX_MAP[prefix]}_{time_hex}{random_suffix}"


def ascending(prefix: IDPrefix, given: str | None = None) -> str:
    """Generate or validate an ascending ID.

    Args:
        prefix: Entity type prefix
        given: If provided, validates it matches the prefix and returns it

    Returns:
        Generated or validated ID
    """
    if given is not None:
        if not given.startswith(PREFIX_MAP[prefix]):
            raise ValueError(f"ID {given} does not start with {PREFIX_MAP[prefix]}")
        return given

    return _create(prefix, descending=False)


def descending(prefix: IDPrefix, given: str | None = None) -> str:
    """Generate or validate a descending ID.

    Args:
        prefix: Entity type prefix
        given: If provided, validates it matches the prefix and returns it

    Returns:
        Generated or validated ID
    """
    if given is not None:
        if not given.startswith(PREFIX_MAP[prefix]):
            raise ValueError(f"ID {given} does not start with {PREFIX_MAP[prefix]}")
        return given

    return _create(prefix, descending=True)


def timestamp(id_str: str) -> int:
    """Extract timestamp from an ascending ID.

    Note: This does NOT work with descending IDs.

    Args:
        id_str: Ascending ID to extract timestamp from

    Returns:
        Timestamp in milliseconds
    """
    # Split on underscore and get hex part
    parts = id_str.split('_')
    if len(parts) != 2:
        raise ValueError(f"Invalid ID format: {id_str}")

    hex_part = parts[1][:12]
    encoded = int(hex_part, 16)

    return encoded // 0x1000


class Identifier:
    """Namespace class for ID generation functions."""

    ascending = staticmethod(ascending)
    descending = staticmethod(descending)
    timestamp = staticmethod(timestamp)
