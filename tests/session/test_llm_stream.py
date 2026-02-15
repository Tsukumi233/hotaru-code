import pytest

from hotaru.provider.provider import ProcessedModelInfo, ProviderInfo
from hotaru.session.llm import LLM, StreamChunk, StreamInput
from hotaru.provider.sdk.anthropic import ToolCall


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
