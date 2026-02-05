"""Error formatting utilities.

Provides functions to format various error types into user-friendly messages.
This will be expanded as more error types are added from other modules.
"""

import json
from typing import Any


def format_error(error: Any) -> str | None:
    """Format known application errors into user-friendly messages.

    Returns None if the error type is not recognized, allowing
    fallback to format_unknown_error.
    """
    # Placeholder for future error type handling
    # Will be expanded as we translate more modules with custom error types

    # Example structure for future implementation:
    # if isinstance(error, MCPFailedError):
    #     return f"MCP server \"{error.name}\" failed..."
    # if isinstance(error, ModelNotFoundError):
    #     return f"Model not found: {error.provider_id}/{error.model_id}"

    return None


def format_unknown_error(error: Any) -> str:
    """Format any error into a string representation.

    Handles Exception objects, serializable objects, and primitives.
    """
    if isinstance(error, Exception):
        # Return stack trace if available
        import traceback
        if hasattr(error, '__traceback__') and error.__traceback__:
            return ''.join(traceback.format_exception(type(error), error, error.__traceback__))
        return f"{error.__class__.__name__}: {str(error)}"

    if isinstance(error, dict) or isinstance(error, list):
        try:
            return json.dumps(error, indent=2)
        except (TypeError, ValueError):
            return "Unexpected error (unserializable)"

    return str(error)
