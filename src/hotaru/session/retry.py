"""Retry helpers for LLM streaming."""

import asyncio
import math
import time
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import Mapping, Optional

try:
    from openai import APIConnectionError as OpenAIAPIConnectionError
    from openai import APITimeoutError as OpenAIAPITimeoutError
except ImportError:
    OpenAIAPIConnectionError = None
    OpenAIAPITimeoutError = None

try:
    from anthropic import APIConnectionError as AnthropicAPIConnectionError
    from anthropic import APITimeoutError as AnthropicAPITimeoutError
except ImportError:
    AnthropicAPIConnectionError = None
    AnthropicAPITimeoutError = None


def _now_ms() -> int:
    return int(time.time() * 1000)


def _float(value: object) -> Optional[float]:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(num):
        return None
    if num < 0:
        return None
    return num


def _status(error: Exception) -> Optional[int]:
    status = getattr(error, "status_code", None)
    if isinstance(status, int):
        return status
    response = getattr(error, "response", None)
    if response is None:
        return None
    code = getattr(response, "status_code", None)
    if isinstance(code, int):
        return code
    if code is None:
        return None
    try:
        return int(code)
    except (TypeError, ValueError):
        return None


def _headers(error: Exception) -> Optional[Mapping[str, str]]:
    response = getattr(error, "response", None)
    if response is None:
        return None
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    if not hasattr(headers, "get"):
        return None
    return headers


def _http_date_ms(value: str) -> Optional[int]:
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    delta = math.ceil(parsed.timestamp() * 1000 - _now_ms())
    if delta <= 0:
        return None
    return int(delta)


class SessionRetry:
    RETRY_INITIAL_DELAY_MS = 2000
    RETRY_BACKOFF_FACTOR = 2
    RETRY_MAX_DELAY_NO_HEADERS_MS = 30_000
    RETRY_MAX_DELAY_MS = 2_147_483_647

    @staticmethod
    async def sleep(ms: int) -> None:
        await asyncio.sleep(max(ms, 0) / 1000)

    @classmethod
    def _header_delay_ms(cls, error: Optional[Exception]) -> Optional[int]:
        if error is None:
            return None
        headers = _headers(error)
        if headers is None:
            return None

        retry_after_ms = _float(headers.get("retry-after-ms"))
        if retry_after_ms is not None:
            return int(math.ceil(retry_after_ms))

        retry_after = headers.get("retry-after")
        if retry_after is None:
            return None

        retry_seconds = _float(retry_after)
        if retry_seconds is not None:
            return int(math.ceil(retry_seconds * 1000))

        return _http_date_ms(retry_after)

    @classmethod
    def delay_ms(cls, attempt: int, error: Optional[Exception]) -> int:
        turn = max(int(attempt), 1)
        header_delay = cls._header_delay_ms(error)
        if header_delay is not None:
            return min(header_delay, cls.RETRY_MAX_DELAY_MS)

        backoff = cls.RETRY_INITIAL_DELAY_MS * (cls.RETRY_BACKOFF_FACTOR ** (turn - 1))
        return min(backoff, cls.RETRY_MAX_DELAY_NO_HEADERS_MS)

    @classmethod
    def retryable(cls, error: Exception) -> bool:
        connection_errors = tuple(
            value
            for value in (
                OpenAIAPIConnectionError,
                OpenAIAPITimeoutError,
                AnthropicAPIConnectionError,
                AnthropicAPITimeoutError,
            )
            if value is not None
        )
        if connection_errors and isinstance(error, connection_errors):
            return True

        code = _status(error)
        if code is None:
            return False
        if code == 429:
            return True
        return 500 <= code <= 599
