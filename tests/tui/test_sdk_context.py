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
