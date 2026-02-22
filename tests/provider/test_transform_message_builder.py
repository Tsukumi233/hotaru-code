import json

from hotaru.provider.transform import ProviderTransform


def test_message_builder_builds_assistant_message_with_tool_calls() -> None:
    msg = ProviderTransform.assistant_tool_message(
        text="thinking...",
        reasoning_text="plan first",
        tool_calls=[
            {"id": "call_1", "name": "read_file", "input": {"path": "README.md"}},
            {"id": "call_2", "name": "list_dir", "input": {"path": "."}},
        ],
    )

    assert msg["role"] == "assistant"
    assert msg["content"] == "thinking..."
    assert msg["reasoning_text"] == "plan first"
    assert len(msg["tool_calls"]) == 2
    assert msg["tool_calls"][0]["id"] == "call_1"
    assert msg["tool_calls"][0]["type"] == "function"
    assert msg["tool_calls"][0]["function"]["name"] == "read_file"
    assert json.loads(msg["tool_calls"][0]["function"]["arguments"]) == {"path": "README.md"}


def test_message_builder_builds_tool_result_messages() -> None:
    done_msg = ProviderTransform.tool_result_message(
        tool_call_id="call_ok",
        status="completed",
        output="ok",
        error=None,
    )
    err_msg = ProviderTransform.tool_result_message(
        tool_call_id="call_err",
        status="error",
        output=None,
        error="boom",
    )
    fallback_msg = ProviderTransform.tool_result_message(
        tool_call_id="call_fallback",
        status="error",
        output=None,
        error=None,
    )

    assert done_msg == {"role": "tool", "tool_call_id": "call_ok", "content": "ok"}
    assert err_msg == {"role": "tool", "tool_call_id": "call_err", "content": "boom"}
    assert fallback_msg == {"role": "tool", "tool_call_id": "call_fallback", "content": "Tool execution failed"}
