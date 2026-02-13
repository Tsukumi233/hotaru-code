import pytest

from hotaru.agent.agent import AgentInfo, AgentMode
from hotaru.session.llm import LLM, StreamChunk
from hotaru.session.processor import SessionProcessor


@pytest.mark.anyio
async def test_processor_disables_tools_when_agent_step_limit_reached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}

    async def fake_stream(cls, stream_input):
        captured["tools"] = stream_input.tools
        captured["messages"] = stream_input.messages
        yield StreamChunk(type="text", text="Step limit reached summary.")

    async def fake_get_agent(cls, name: str):
        return AgentInfo(
            name=name,
            mode=AgentMode.PRIMARY,
            permission=[],
            steps=1,
            options={},
        )

    monkeypatch.setattr(LLM, "stream", classmethod(fake_stream))
    monkeypatch.setattr("hotaru.agent.agent.Agent.get", classmethod(fake_get_agent))

    processor = SessionProcessor(
        session_id="ses_test",
        model_id="model",
        provider_id="provider",
        agent="build",
        cwd="/tmp",
        worktree="/tmp",
    )

    result = await processor.process(user_message="Please analyze this code.")

    assert result.status == "stop"
    assert captured["tools"] is None
    assert any(
        msg.get("role") == "assistant" and "MAXIMUM STEPS REACHED" in str(msg.get("content", ""))
        for msg in captured["messages"]
    )
