from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import httpx

from anthropic import (
    APIConnectionError as AnthropicAPIConnectionError,
    APIStatusError as AnthropicAPIStatusError,
)
from openai import (
    APIConnectionError as OpenAIAPIConnectionError,
    APIStatusError as OpenAIAPIStatusError,
)

from hotaru.session.retry import SessionRetry


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://example.com/v1/chat/completions")


def _response(
    status: int = 429,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        request=_request(),
        headers=headers,
    )


def test_retry_delay_uses_exponential_backoff_without_headers() -> None:
    assert SessionRetry.delay_ms(1, None) == 2000
    assert SessionRetry.delay_ms(2, None) == 4000
    assert SessionRetry.delay_ms(3, None) == 8000
    assert SessionRetry.delay_ms(5, None) == 30000


def test_retry_delay_prefers_retry_after_ms_header() -> None:
    error = OpenAIAPIStatusError(
        "rate limited",
        response=_response(headers={"retry-after-ms": "1500", "retry-after": "99"}),
        body={},
    )
    assert SessionRetry.delay_ms(1, error) == 1500


def test_retry_delay_reads_retry_after_seconds_header() -> None:
    error = AnthropicAPIStatusError(
        "rate limited",
        response=_response(headers={"retry-after": "2.4"}),
        body={},
    )
    assert SessionRetry.delay_ms(1, error) == 2400


def test_retry_delay_reads_retry_after_http_date_header(monkeypatch) -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    header = format_datetime(now + timedelta(seconds=5), usegmt=True)
    error = OpenAIAPIStatusError(
        "rate limited",
        response=_response(headers={"retry-after": header}),
        body={},
    )
    monkeypatch.setattr("hotaru.session.retry._now_ms", lambda: int(now.timestamp() * 1000))
    assert SessionRetry.delay_ms(1, error) == 5000


def test_retryable_covers_transient_sdk_errors() -> None:
    request = _request()
    openai_connection = OpenAIAPIConnectionError(message="no route", request=request)
    anthropic_connection = AnthropicAPIConnectionError(message="no route", request=request)
    openai_rate_limit = OpenAIAPIStatusError("rate", response=_response(status=429), body={})
    anthropic_upstream = AnthropicAPIStatusError("upstream", response=_response(status=503), body={})
    openai_bad_request = OpenAIAPIStatusError("bad request", response=_response(status=400), body={})

    assert SessionRetry.retryable(openai_connection) is True
    assert SessionRetry.retryable(anthropic_connection) is True
    assert SessionRetry.retryable(openai_rate_limit) is True
    assert SessionRetry.retryable(anthropic_upstream) is True
    assert SessionRetry.retryable(openai_bad_request) is False
