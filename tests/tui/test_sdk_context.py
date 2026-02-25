import asyncio

import pytest

from hotaru.api_client import ApiClientError
from hotaru.tui.context.sdk import SDKContext


class _ApiClientStub:
    async def send_session_message(self, _session_id: str, _payload: dict):
        raise RuntimeError("request failed")

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


class _ApiMissingIdleStub:
    def __init__(self) -> None:
        self._events: asyncio.Queue[dict] = asyncio.Queue()

    async def send_session_message(self, session_id: str, _payload: dict):
        await self._events.put(
            {
                "type": "message.part.updated",
                "data": {
                    "part": {
                        "id": "part_1",
                        "session_id": session_id,
                        "message_id": "message_1",
                        "type": "text",
                        "text": "hello",
                    }
                },
            }
        )
        return {"ok": True}

    async def stream_events(self):
        while True:
            event = await self._events.get()
            yield event


class _ApiReadyStreamStub:
    def __init__(self) -> None:
        self.closed = False
        self.cancelled = False

    async def stream_events(self):
        yield {"type": "server.connected", "data": {}}
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            self.cancelled = True
            raise

    async def aclose(self) -> None:
        self.closed = True


class _ApiFlakyEventStreamStub:
    def __init__(self, failures: int = 3) -> None:
        self.failures = failures
        self.started = 0
        self.cancelled = False
        self._stop = asyncio.Event()

    async def stream_events(self):
        self.started += 1
        if self.started <= self.failures:
            raise RuntimeError(f"connection failed {self.started}")
        yield {"type": "runtime", "data": {"state": "ready"}}
        try:
            await self._stop.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


class _ApiAlwaysFailEventStreamStub:
    def __init__(self) -> None:
        self.started = 0

    async def stream_events(self):
        self.started += 1
        raise RuntimeError("server offline")
        yield  # pragma: no cover


@pytest.mark.anyio
async def test_send_message_emits_error_event_when_api_request_fails(tmp_path) -> None:
    sdk = SDKContext(cwd=str(tmp_path), api_client=_ApiClientStub())
    events = [event async for event in sdk.send_message(session_id="session_1", content="hello")]
    assert events == [{"type": "error", "data": {"error": "request failed"}}]


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


@pytest.mark.anyio
async def test_send_message_finishes_without_idle_when_status_event_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr("hotaru.tui.context.sdk._SEND_MESSAGE_IDLE_TIMEOUT", 0.3)
    sdk = SDKContext(cwd=str(tmp_path), api_client=_ApiMissingIdleStub())
    events = [event async for event in sdk.send_message(session_id="session_1", content="hello")]
    await sdk.aclose()

    assert [event["type"] for event in events] == ["message.part.updated"]


@pytest.mark.anyio
async def test_start_event_stream_does_not_manage_server_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from hotaru.server.server import Server, ServerInfo

    info = ServerInfo(host="127.0.0.1", port=4096)
    starts: list[bool] = []
    stops: list[bool] = []

    def fake_info(cls):
        return info

    async def fake_start(cls, host: str = "127.0.0.1", port: int = 4096):
        starts.append(True)
        return ServerInfo(host=host, port=port)

    async def fake_stop(cls) -> None:
        stops.append(True)

    monkeypatch.setattr(Server, "info", classmethod(fake_info))
    monkeypatch.setattr(Server, "start", classmethod(fake_start))
    monkeypatch.setattr(Server, "stop", classmethod(fake_stop))
    monkeypatch.setattr(SDKContext, "_build_default_api_client", staticmethod(lambda _cwd: _ApiReadyStreamStub()))

    sdk = SDKContext(cwd=str(tmp_path))
    await sdk.start_event_stream()
    await sdk.aclose()

    assert starts == []
    assert stops == []


@pytest.mark.anyio
async def test_event_stream_uses_exponential_backoff_and_emits_connection_events(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    api = _ApiFlakyEventStreamStub(failures=3)
    sdk = SDKContext(cwd=str(tmp_path), api_client=api)
    states: list[dict] = []
    delays: list[float] = []
    wait = asyncio.sleep

    async def fake_sleep(delay: float) -> None:
        delays.append(float(delay))
        await wait(0)

    monkeypatch.setattr("hotaru.tui.context.sdk.asyncio.sleep", fake_sleep)
    sdk.on_event("server.connection", lambda data: states.append(dict(data)))

    await sdk.start_event_stream()
    await sdk.aclose()

    assert delays[:3] == [0.25, 0.5, 1.0]
    assert [item.get("state") for item in states[:4]] == [
        "retrying",
        "retrying",
        "retrying",
        "connected",
    ]


@pytest.mark.anyio
async def test_event_stream_stops_after_retry_limit_and_emits_exhausted_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    api = _ApiAlwaysFailEventStreamStub()
    sdk = SDKContext(cwd=str(tmp_path), api_client=api)
    states: list[dict] = []
    wait = asyncio.sleep

    async def fake_sleep(_delay: float) -> None:
        await wait(0)

    monkeypatch.setattr("hotaru.tui.context.sdk.asyncio.sleep", fake_sleep)
    monkeypatch.setattr("hotaru.tui.context.sdk._EVENT_STREAM_MAX_RETRIES", 3)
    sdk.on_event("server.connection", lambda data: states.append(dict(data)))

    await asyncio.wait_for(sdk._run_event_stream(), timeout=0.2)

    assert api.started == 3
    assert states[-1] == {"state": "exhausted", "attempt": 3}
