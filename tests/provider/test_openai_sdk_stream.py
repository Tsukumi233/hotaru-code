from types import SimpleNamespace

import pytest

from hotaru.provider.sdk.openai import OpenAISDK


class _AsyncStream:
    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        self._iter = iter(self._chunks)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


def _chunk(*, choices, usage=None):
    return SimpleNamespace(choices=choices, usage=usage)


@pytest.mark.anyio
async def test_openai_stream_assembles_multiple_tool_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    chunks = [
        _chunk(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                index=0,
                                id="call_1",
                                function=SimpleNamespace(name="read", arguments='{"filePath":"READ'),
                            )
                        ],
                    ),
                    finish_reason=None,
                )
            ]
        ),
        _chunk(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                index=0,
                                id=None,
                                function=SimpleNamespace(name=None, arguments='ME.md"}'),
                            ),
                            SimpleNamespace(
                                index=1,
                                id="call_2",
                                function=SimpleNamespace(name="grep", arguments='{"pattern":"TODO"}'),
                            ),
                        ],
                    ),
                    finish_reason=None,
                )
            ]
        ),
        _chunk(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=None, tool_calls=None),
                    finish_reason="tool_calls",
                )
            ]
        ),
        _chunk(
            choices=[],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=4),
        ),
    ]

    class _FakeCompletions:
        async def create(self, **_kwargs):
            return _AsyncStream(chunks)

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            self.chat = SimpleNamespace(completions=_FakeCompletions())

    monkeypatch.setattr("hotaru.provider.sdk.openai.AsyncOpenAI", _FakeClient)

    sdk = OpenAISDK(api_key="test-key")
    seen = [chunk async for chunk in sdk.stream(model="gpt-5", messages=[{"role": "user", "content": "hi"}])]

    starts = [c for c in seen if c.type == "tool_call_start"]
    deltas = [c for c in seen if c.type == "tool_call_delta"]
    ends = [c for c in seen if c.type == "tool_call_end"]
    usage = [c for c in seen if c.type == "message_delta" and c.usage]

    assert len(starts) == 2
    assert starts[0].tool_call_id == "call_1"
    assert starts[1].tool_call_id == "call_2"
    assert len(deltas) >= 2
    assert len(ends) == 2
    assert ends[0].tool_call.id == "call_1"
    assert ends[0].tool_call.input == {"filePath": "README.md"}
    assert ends[1].tool_call.id == "call_2"
    assert usage[-1].usage == {"input_tokens": 10, "output_tokens": 4}


@pytest.mark.anyio
async def test_openai_stream_emits_reasoning_events(monkeypatch: pytest.MonkeyPatch) -> None:
    chunks = [
        _chunk(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content=None,
                        tool_calls=None,
                        reasoning="First thought.",
                    ),
                    finish_reason=None,
                )
            ]
        ),
        _chunk(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=None, tool_calls=None),
                    finish_reason="stop",
                )
            ]
        ),
    ]

    class _FakeCompletions:
        async def create(self, **_kwargs):
            return _AsyncStream(chunks)

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            self.chat = SimpleNamespace(completions=_FakeCompletions())

    monkeypatch.setattr("hotaru.provider.sdk.openai.AsyncOpenAI", _FakeClient)

    sdk = OpenAISDK(api_key="test-key")
    seen = [chunk async for chunk in sdk.stream(model="gpt-5", messages=[{"role": "user", "content": "hi"}])]

    event_types = [chunk.type for chunk in seen]
    assert "reasoning_start" in event_types
    assert "reasoning_delta" in event_types
    assert "reasoning_end" in event_types
    delta = next(chunk for chunk in seen if chunk.type == "reasoning_delta")
    assert delta.reasoning_text == "First thought."
