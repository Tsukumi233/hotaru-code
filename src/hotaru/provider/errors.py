"""SDK-agnostic error classification.

Classifies provider errors by fully-qualified type name so the session
layer never needs to import SDK packages directly.
"""

# Fully-qualified type names of errors that are always recoverable.
_RECOVERABLE_TYPES: frozenset[str] = frozenset({
    "openai.APIError",
    "openai.APIConnectionError",
    "openai.APIStatusError",
    "openai.APITimeoutError",
    "openai.RateLimitError",
    "anthropic.APIError",
    "anthropic.APIConnectionError",
    "anthropic.APIStatusError",
    "anthropic.APITimeoutError",
    "anthropic.RateLimitError",
})

# Connection-class errors eligible for automatic retry.
_RETRYABLE_TYPES: frozenset[str] = frozenset({
    "openai.APIConnectionError",
    "openai.APITimeoutError",
    "anthropic.APIConnectionError",
    "anthropic.APITimeoutError",
})


def _fqn(error: Exception) -> str:
    cls = type(error)
    module = getattr(cls, "__module__", "") or ""
    # Normalise private sub-modules (e.g. openai._exceptions → openai)
    top = module.split(".")[0]
    return f"{top}.{cls.__qualname__}"


def _status(error: Exception) -> int | None:
    code = getattr(error, "status_code", None)
    if isinstance(code, int):
        return code
    response = getattr(error, "response", None)
    if response is None:
        return None
    code = getattr(response, "status_code", None)
    if isinstance(code, int):
        return code
    try:
        return int(code)
    except (TypeError, ValueError):
        return None


def recoverable(error: Exception) -> bool:
    """Return True if the error is a recoverable provider error."""
    if isinstance(error, (TimeoutError,)):
        return True
    if _fqn(error) in _RECOVERABLE_TYPES:
        return True
    return retryable(error)


def retryable(error: Exception) -> bool:
    """Return True if the error is eligible for automatic retry."""
    if _fqn(error) in _RETRYABLE_TYPES:
        return True
    code = _status(error)
    if code is None:
        return False
    if code == 429:
        return True
    return 500 <= code <= 599
