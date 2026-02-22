import pytest

from hotaru.provider.provider import ProcessedModelInfo, ProviderInfo
from hotaru.session.llm import LLM, StreamChunk, StreamInput
from hotaru.provider.sdk.anthropic import ToolCall
from hotaru.session.retry import SessionRetry


class _StatusError(Exception):
    def __init__(self, status: int, headers: dict[str, str] | None = None):
        super().__init__(f"status={status}")
        self.response = type("Response", (), {"status_code": status, "headers": headers or {}})()


@pytest.mark.anyio
async def test_llm_anthropic_tool_roundtrip_and_finish_reason_normalized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ProviderInfo(
        id="anthropic",
        name="Anthropic",
        env=[],
        key="test-key",
        models={
            "claude-sonnet": ProcessedModelInfo(
                id="claude-sonnet",
                provider_id="anthropic",
                name="claude-sonnet",
                api_id="claude-sonnet",
                api_type="anthropic",
            )
        },
    )

    async def fake_get_provider(cls, provider_id: str):
        if provider_id == "anthropic":
            return provider
        return None

    captured = {}

    async def fake_anthropic_stream(
        cls,
        *,
        api_key,
        model,
        messages,
        base_url=None,
        system=None,
        tools=None,
        tool_choice=None,
        max_tokens=4096,
        temperature=None,
        top_p=None,
        options=None,
    ):
        captured["messages"] = messages
        captured["tools"] = tools
        captured["tool_choice"] = tool_choice
        yield StreamChunk(type="tool_call_start", tool_call_id="call_1", tool_call_name="read")
        yield StreamChunk(type="tool_call_end", tool_call=ToolCall(id="call_1", name="read", input={"filePath": "README.md"}))
        yield StreamChunk(type="message_delta", usage={"input_tokens": 3, "output_tokens": 2}, stop_reason="tool_use")

    monkeypatch.setattr("hotaru.provider.provider.Provider.get", classmethod(fake_get_provider))
    monkeypatch.setattr(LLM, "_stream_anthropic", classmethod(fake_anthropic_stream))

    result = await LLM.complete(
        StreamInput(
            session_id="s1",
            provider_id="anthropic",
            model_id="claude-sonnet",
            messages=[{"role": "user", "content": "read file"}],
            system=["sys-a", "sys-b"],
            tools={
                "read": {
                    "description": "Read file",
                    "parameters": {"type": "object", "properties": {"filePath": {"type": "string"}}},
                }
            },
            tool_choice="required",
        )
    )

    assert result.stop_reason == "tool-calls"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "read"
    assert captured["tool_choice"] == "required"
    assert captured["messages"][0]["role"] == "user"


@pytest.mark.anyio
async def test_llm_passes_through_reasoning_events(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = ProviderInfo(
        id="anthropic",
        name="Anthropic",
        env=[],
        key="test-key",
        models={
            "claude-sonnet": ProcessedModelInfo(
                id="claude-sonnet",
                provider_id="anthropic",
                name="claude-sonnet",
                api_id="claude-sonnet",
                api_type="anthropic",
            )
        },
    )

    async def fake_get_provider(cls, provider_id: str):
        if provider_id == "anthropic":
            return provider
        return None

    async def fake_anthropic_stream(
        cls,
        *,
        api_key,
        model,
        messages,
        base_url=None,
        system=None,
        tools=None,
        tool_choice=None,
        max_tokens=4096,
        temperature=None,
        top_p=None,
        options=None,
    ):
        yield StreamChunk(type="reasoning_start", reasoning_id="r1")
        yield StreamChunk(type="reasoning_delta", reasoning_id="r1", reasoning_text="plan")
        yield StreamChunk(type="reasoning_end", reasoning_id="r1")
        yield StreamChunk(type="message_delta", stop_reason="stop")

    monkeypatch.setattr("hotaru.provider.provider.Provider.get", classmethod(fake_get_provider))
    monkeypatch.setattr(LLM, "_stream_anthropic", classmethod(fake_anthropic_stream))

    seen = [
        chunk
        async for chunk in LLM.stream(
            StreamInput(
                session_id="s1",
                provider_id="anthropic",
                model_id="claude-sonnet",
                messages=[{"role": "user", "content": "hi"}],
            )
        )
    ]

    types = [chunk.type for chunk in seen]
    assert types.count("reasoning_start") == 1
    assert types.count("reasoning_delta") == 1
    assert types.count("reasoning_end") == 1


@pytest.mark.anyio
async def test_llm_retries_retryable_error_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = ProviderInfo(
        id="openai",
        name="OpenAI",
        env=[],
        key="test-key",
        models={
            "gpt-5": ProcessedModelInfo(
                id="gpt-5",
                provider_id="openai",
                name="gpt-5",
                api_id="gpt-5",
                api_type="openai",
            )
        },
    )
    calls = {"count": 0}
    slept: list[int] = []

    async def fake_get_provider(cls, provider_id: str):
        if provider_id == "openai":
            return provider
        return None

    async def fake_openai_stream(
        cls,
        *,
        api_key,
        model,
        messages,
        base_url=None,
        system=None,
        tools=None,
        tool_choice=None,
        max_tokens=4096,
        temperature=None,
        top_p=None,
        options=None,
    ):
        calls["count"] += 1
        if calls["count"] == 1:
            raise _StatusError(429, {"retry-after-ms": "7"})
        yield StreamChunk(type="message_delta", stop_reason="stop")

    async def fake_sleep(ms: int) -> None:
        slept.append(ms)

    monkeypatch.setattr("hotaru.provider.provider.Provider.get", classmethod(fake_get_provider))
    monkeypatch.setattr(LLM, "_stream_openai", classmethod(fake_openai_stream))
    monkeypatch.setattr(SessionRetry, "sleep", staticmethod(fake_sleep))

    seen = [
        chunk
        async for chunk in LLM.stream(
            StreamInput(
                session_id="s1",
                provider_id="openai",
                model_id="gpt-5",
                messages=[{"role": "user", "content": "hi"}],
                retries=2,
            )
        )
    ]

    assert calls["count"] == 2
    assert slept == [7]
    assert seen[-1].type == "message_delta"
    assert seen[-1].stop_reason == "stop"


@pytest.mark.anyio
async def test_llm_does_not_retry_non_retryable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = ProviderInfo(
        id="openai",
        name="OpenAI",
        env=[],
        key="test-key",
        models={
            "gpt-5": ProcessedModelInfo(
                id="gpt-5",
                provider_id="openai",
                name="gpt-5",
                api_id="gpt-5",
                api_type="openai",
            )
        },
    )
    calls = {"count": 0}
    slept: list[int] = []

    async def fake_get_provider(cls, provider_id: str):
        if provider_id == "openai":
            return provider
        return None

    async def fake_openai_stream(
        cls,
        *,
        api_key,
        model,
        messages,
        base_url=None,
        system=None,
        tools=None,
        tool_choice=None,
        max_tokens=4096,
        temperature=None,
        top_p=None,
        options=None,
    ):
        calls["count"] += 1
        raise _StatusError(400)
        yield StreamChunk(type="message_delta", stop_reason="stop")

    async def fake_sleep(ms: int) -> None:
        slept.append(ms)

    monkeypatch.setattr("hotaru.provider.provider.Provider.get", classmethod(fake_get_provider))
    monkeypatch.setattr(LLM, "_stream_openai", classmethod(fake_openai_stream))
    monkeypatch.setattr(SessionRetry, "sleep", staticmethod(fake_sleep))

    seen = [
        chunk
        async for chunk in LLM.stream(
            StreamInput(
                session_id="s1",
                provider_id="openai",
                model_id="gpt-5",
                messages=[{"role": "user", "content": "hi"}],
                retries=2,
            )
        )
    ]

    assert calls["count"] == 1
    assert slept == []
    assert seen[-1].type == "error"
    assert "status=400" in str(seen[-1].error)


@pytest.mark.anyio
async def test_llm_stops_after_retry_budget_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = ProviderInfo(
        id="openai",
        name="OpenAI",
        env=[],
        key="test-key",
        models={
            "gpt-5": ProcessedModelInfo(
                id="gpt-5",
                provider_id="openai",
                name="gpt-5",
                api_id="gpt-5",
                api_type="openai",
            )
        },
    )
    calls = {"count": 0}
    slept: list[int] = []

    async def fake_get_provider(cls, provider_id: str):
        if provider_id == "openai":
            return provider
        return None

    async def fake_openai_stream(
        cls,
        *,
        api_key,
        model,
        messages,
        base_url=None,
        system=None,
        tools=None,
        tool_choice=None,
        max_tokens=4096,
        temperature=None,
        top_p=None,
        options=None,
    ):
        calls["count"] += 1
        raise _StatusError(503)
        yield StreamChunk(type="message_delta", stop_reason="stop")

    async def fake_sleep(ms: int) -> None:
        slept.append(ms)

    monkeypatch.setattr("hotaru.provider.provider.Provider.get", classmethod(fake_get_provider))
    monkeypatch.setattr(LLM, "_stream_openai", classmethod(fake_openai_stream))
    monkeypatch.setattr(SessionRetry, "sleep", staticmethod(fake_sleep))

    seen = [
        chunk
        async for chunk in LLM.stream(
            StreamInput(
                session_id="s1",
                provider_id="openai",
                model_id="gpt-5",
                messages=[{"role": "user", "content": "hi"}],
                retries=2,
            )
        )
    ]

    assert calls["count"] == 3
    assert slept == [2000, 4000]
    assert seen[-1].type == "error"
    assert "status=503" in str(seen[-1].error)


@pytest.mark.anyio
async def test_llm_kimi_default_omits_temperature_but_keeps_top_p(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = ProviderInfo(
        id="moonshot",
        name="Moonshot",
        env=[],
        key="test-key",
        models={
            "kimi-k2.5": ProcessedModelInfo(
                id="kimi-k2.5",
                provider_id="moonshot",
                name="kimi-k2.5",
                api_id="kimi-k2.5",
                api_type="openai",
            )
        },
    )
    captured: dict[str, object] = {}

    async def fake_get_provider(cls, provider_id: str):
        if provider_id == "moonshot":
            return provider
        return None

    async def fake_openai_stream(
        cls,
        *,
        api_key,
        model,
        messages,
        base_url=None,
        system=None,
        tools=None,
        tool_choice=None,
        max_tokens=4096,
        temperature=None,
        top_p=None,
        options=None,
    ):
        captured["temperature"] = temperature
        captured["top_p"] = top_p
        yield StreamChunk(type="message_delta", stop_reason="stop")

    monkeypatch.setattr("hotaru.provider.provider.Provider.get", classmethod(fake_get_provider))
    monkeypatch.setattr(LLM, "_stream_openai", classmethod(fake_openai_stream))

    seen = [
        chunk
        async for chunk in LLM.stream(
            StreamInput(
                session_id="s1",
                provider_id="moonshot",
                model_id="kimi-k2.5",
                messages=[{"role": "user", "content": "hi"}],
            )
        )
    ]

    assert seen[-1].type == "message_delta"
    assert captured["temperature"] is None
    assert captured["top_p"] == 0.95
