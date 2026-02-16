from hotaru.provider.models import ModelCapabilities
from hotaru.provider.provider import ProcessedModelInfo
from hotaru.provider.transform import ProviderTransform


def _model(
    *,
    provider_id: str = "moonshot",
    model_id: str = "kimi-k2.5",
    interleaved_field: str | None = "reasoning_content",
    variants: dict[str, dict] | None = None,
) -> ProcessedModelInfo:
    capabilities = ModelCapabilities()
    if interleaved_field:
        capabilities.interleaved = {"field": interleaved_field}

    return ProcessedModelInfo(
        id=model_id,
        provider_id=provider_id,
        name=model_id,
        api_id=model_id,
        api_type="openai",
        capabilities=capabilities,
        variants=variants or {},
    )


def test_message_maps_reasoning_parts_to_interleaved_field() -> None:
    messages = [
        {
            "role": "assistant",
            "content": [
                {"type": "reasoning", "text": "let me think"},
                {"type": "text", "text": "final answer"},
            ],
        }
    ]

    transformed = ProviderTransform.message(
        messages,
        model=_model(),
        provider_id="moonshot",
        model_id="kimi-k2.5",
        api_type="openai",
    )

    assert transformed[0]["reasoning_content"] == "let me think"
    assert transformed[0]["content"] == [{"type": "text", "text": "final answer"}]


def test_message_keeps_non_interleaved_model_unchanged() -> None:
    messages = [{"role": "assistant", "content": [{"type": "reasoning", "text": "x"}]}]

    transformed = ProviderTransform.message(
        messages,
        model=_model(interleaved_field=None),
        provider_id="openai",
        model_id="gpt-4o-mini",
        api_type="openai",
    )

    assert "reasoning_content" not in transformed[0]
    assert transformed[0]["content"] == [{"type": "reasoning", "text": "x"}]


def test_message_sets_empty_interleaved_field_for_assistant_tool_calls() -> None:
    messages = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "read", "arguments": "{}"},
                }
            ],
        }
    ]

    transformed = ProviderTransform.message(
        messages,
        model=_model(),
        provider_id="moonshot",
        model_id="kimi-k2.5",
        api_type="openai",
    )

    assert transformed[0]["reasoning_content"] == ""


def test_resolve_variant_reads_model_variants() -> None:
    model = _model(
        provider_id="demo",
        model_id="demo-model",
        variants={"high": {"thinking": {"type": "enabled", "budgetTokens": 16000}}},
    )
    resolved = ProviderTransform.resolve_variant(model=model, variant="high")
    assert resolved == {"thinking": {"type": "enabled", "budgetTokens": 16000}}
