from hotaru.tui.header_usage import compute_session_header_usage


def _assistant_message(
    *,
    provider_id: str,
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    reasoning_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    cost: float = 0.0,
) -> dict:
    return {
        "role": "assistant",
        "info": {
            "cost": cost,
            "model": {"provider_id": provider_id, "model_id": model_id},
            "tokens": {
                "input": input_tokens,
                "output": output_tokens,
                "reasoning": reasoning_tokens,
                "cache_read": cache_read_tokens,
                "cache_write": cache_write_tokens,
            },
        },
    }


def test_compute_session_header_usage_matches_opencode_semantics() -> None:
    messages = [
        _assistant_message(
            provider_id="moonshot",
            model_id="kimi-k2.5",
            input_tokens=8,
            output_tokens=4,
            reasoning_tokens=2,
            cache_read_tokens=1,
            cache_write_tokens=0,
            cost=0.1,
        ),
        _assistant_message(
            provider_id="moonshot",
            model_id="kimi-k2.5",
            input_tokens=100,
            output_tokens=50,
            reasoning_tokens=25,
            cache_read_tokens=10,
            cache_write_tokens=15,
            cost=0.2,
        ),
    ]
    providers = [
        {
            "id": "moonshot",
            "models": {
                "kimi-k2.5": {
                    "limit": {"context": 1000, "output": 32000},
                }
            },
        }
    ]

    usage = compute_session_header_usage(messages=messages, providers=providers)

    assert usage.context_info == "200  20%"
    assert usage.cost == "$0.3000"


def test_compute_session_header_usage_uses_latest_assistant_with_output() -> None:
    messages = [
        _assistant_message(
            provider_id="moonshot",
            model_id="kimi-k2.5",
            input_tokens=12,
            output_tokens=6,
            reasoning_tokens=3,
            cost=0.1,
        ),
        _assistant_message(
            provider_id="moonshot",
            model_id="kimi-k2.5",
            input_tokens=999,
            output_tokens=0,
            reasoning_tokens=999,
            cost=0.2,
        ),
    ]
    providers = [{"id": "moonshot", "models": {"kimi-k2.5": {}}}]

    usage = compute_session_header_usage(messages=messages, providers=providers)

    assert usage.context_info == "21"
    assert usage.cost == "$0.3000"


def test_compute_session_header_usage_returns_empty_context_without_output() -> None:
    messages = [
        _assistant_message(
            provider_id="moonshot",
            model_id="kimi-k2.5",
            input_tokens=5,
            output_tokens=0,
            reasoning_tokens=4,
            cost=0.02,
        )
    ]

    usage = compute_session_header_usage(messages=messages, providers=[])

    assert usage.context_info == ""
    assert usage.cost == "$0.0200"
