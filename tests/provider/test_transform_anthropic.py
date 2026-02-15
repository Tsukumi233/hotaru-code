from hotaru.provider.transform import (
    anthropic_messages,
    anthropic_tools,
    normalize_messages,
    normalize_tool_call_id,
)


def test_anthropic_tools_conversion() -> None:
    tools = [
        {
            "type": "function",
            "function": {
                "name": "read",
                "description": "Read file",
                "parameters": {"type": "object", "properties": {"filePath": {"type": "string"}}},
            },
        }
    ]
    converted = anthropic_tools(tools)
    assert converted is not None
    assert converted[0]["name"] == "read"
    assert converted[0]["input_schema"]["type"] == "object"


def test_anthropic_messages_conversion_with_tool_roundtrip() -> None:
    messages = [
        {"role": "user", "content": "open file"},
        {
            "role": "assistant",
            "content": "calling tool",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "read", "arguments": "{\"filePath\":\"README.md\"}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "file contents"},
    ]

    converted = anthropic_messages(messages)
    assert len(converted) == 3
    assert converted[0]["role"] == "user"
    assert converted[1]["role"] == "assistant"
    blocks = converted[1]["content"]
    assert blocks[0]["type"] == "text"
    assert blocks[1]["type"] == "tool_use"
    assert blocks[1]["input"]["filePath"] == "README.md"
    assert converted[2]["role"] == "user"
    assert converted[2]["content"][0]["type"] == "tool_result"


def test_normalize_tool_call_id_for_claude() -> None:
    normalized = normalize_tool_call_id("call:1/alpha", provider_id="anthropic", model_id="claude-sonnet")
    assert normalized == "call_1_alpha"


def test_normalize_messages_filters_empty_anthropic_messages() -> None:
    messages = [
        {"role": "assistant", "content": ""},
        {"role": "assistant", "content": "hello"},
    ]
    normalized = normalize_messages(
        messages,
        provider_id="anthropic",
        model_id="claude-sonnet",
        api_type="anthropic",
    )
    assert len(normalized) == 1
    assert normalized[0]["content"] == "hello"


def test_normalize_messages_inserts_assistant_between_tool_and_user_for_mistral() -> None:
    messages = [
        {"role": "assistant", "content": None, "tool_calls": [{"id": "call!1", "function": {"name": "read", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call!1", "content": "ok"},
        {"role": "user", "content": "next"},
    ]
    normalized = normalize_messages(
        messages,
        provider_id="mistral",
        model_id="mistral-large",
        api_type="openai",
    )
    assert normalized[1]["tool_call_id"] == "call10000"
    assert normalized[2]["role"] == "assistant"
    assert normalized[3]["role"] == "user"
