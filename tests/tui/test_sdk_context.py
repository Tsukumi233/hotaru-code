import asyncio

import pytest

from hotaru.api_client import ApiClientError
from hotaru.tui.context.sdk import SDKContext


class _ApiClientStub:
    async def stream_session_message(self, _session_id: str, _payload: dict):
        raise RuntimeError("stream failed")
        yield  # pragma: no cover

    async def get_session(self, _session_id: str):
        raise ApiClientError(status_code=404, message="not found")

    async def list_providers(self):
        return [
            {
                "id": "openai",
                "name": "OpenAI",
                "models": [
                    {"id": "gpt-5", "name": "GPT-5", "api_id": "gpt-5"},
                ],
            }
        ]

    async def list_provider_models(self, _provider_id: str):
        return []


class _ApiEventStreamStub:
    def __init__(self) -> None:
        self.closed = False
        self.cancelled = False
        self.started = 0

    async def stream_events(self):
        self.started += 1
        yield {"type": "runtime", "data": {"state": "ready"}}
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            self.cancelled = True
            raise

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.anyio
async def test_send_message_emits_error_event_when_api_stream_fails(tmp_path) -> None:
    sdk = SDKContext(cwd=str(tmp_path), api_client=_ApiClientStub())
    events = [event async for event in sdk.send_message(session_id="session_1", content="hello")]
    assert events == [{"type": "error", "data": {"error": "stream failed"}}]


@pytest.mark.anyio
async def test_get_session_returns_none_when_api_reports_not_found(tmp_path) -> None:
    sdk = SDKContext(cwd=str(tmp_path), api_client=_ApiClientStub())
    assert await sdk.get_session("missing") is None


@pytest.mark.anyio
async def test_list_providers_normalizes_model_payload_shape(tmp_path) -> None:
    sdk = SDKContext(cwd=str(tmp_path), api_client=_ApiClientStub())
    providers = await sdk.list_providers()
    assert providers == [
        {
            "id": "openai",
            "name": "OpenAI",
            "models": {
                "gpt-5": {
                    "id": "gpt-5",
                    "name": "GPT-5",
                    "api_id": "gpt-5",
                    "limit": {"context": 0, "output": 0},
                }
            },
        }
    ]


def test_event_subscription_and_emit_unsubscribe(tmp_path) -> None:
    sdk = SDKContext(cwd=str(tmp_path))
    observed: list[dict] = []

    unsubscribe = sdk.on_event("runtime", lambda data: observed.append(data))
    sdk.emit_event("runtime", {"state": "ready"})
    unsubscribe()
    sdk.emit_event("runtime", {"state": "stopped"})

    assert observed == [{"state": "ready"}]


@pytest.mark.anyio
async def test_event_stream_lifecycle_starts_and_stops_with_context(tmp_path) -> None:
    api = _ApiEventStreamStub()
    sdk = SDKContext(cwd=str(tmp_path), api_client=api)
    observed: list[dict] = []

    sdk.on_event("runtime", lambda data: observed.append(data))
    await sdk.start_event_stream()
    await asyncio.sleep(0.05)
    await sdk.aclose()

    assert observed == [{"state": "ready"}]
    assert api.started == 1
    assert api.cancelled is True
