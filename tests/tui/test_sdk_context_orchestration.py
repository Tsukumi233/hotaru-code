import pytest

from hotaru.tui.context.sdk import SDKContext


class _ApiRecorder:
    def __init__(self) -> None:
        self.compact_payload: dict | None = None
        self.create_payload: dict | None = None

    async def compact_session(self, _session_id: str, payload: dict | None = None):
        self.compact_payload = payload or {}
        return {"status": "stop"}

    async def create_session(self, payload: dict):
        self.create_payload = payload
        return {"id": "session_1", "time": {"created": 1, "updated": 1}}


@pytest.mark.anyio
async def test_compact_session_maps_provider_model_override_into_payload(tmp_path) -> None:
    api = _ApiRecorder()
    sdk = SDKContext(cwd=str(tmp_path), api_client=api)

    result = await sdk.compact_session("session_1", model="openai/gpt-5")

    assert result == {"status": "stop"}
    assert api.compact_payload == {
        "model": "openai/gpt-5",
        "provider_id": "openai",
        "model_id": "gpt-5",
    }


@pytest.mark.anyio
async def test_create_session_includes_cwd_in_api_payload(tmp_path) -> None:
    api = _ApiRecorder()
    sdk = SDKContext(cwd=str(tmp_path), api_client=api)

    await sdk.create_session(agent="build", model="openai/gpt-5", title="Demo")

    assert api.create_payload == {
        "agent": "build",
        "model": "openai/gpt-5",
        "title": "Demo",
        "cwd": str(tmp_path),
    }
