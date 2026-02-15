from hotaru.provider.provider import ProcessedModelInfo
from hotaru.session.system import SystemPrompt


def _model(model_id: str, provider_id: str = "openai", family: str | None = None, api_type: str = "openai"):
    return ProcessedModelInfo(
        id=model_id,
        provider_id=provider_id,
        name=model_id,
        family=family,
        api_id=model_id,
        api_type=api_type,  # type: ignore[arg-type]
    )


def test_for_model_gpt5_path() -> None:
    prompts = SystemPrompt.for_model(_model("gpt-5"))
    assert len(prompts) >= 2
    assert "GPT-5 family" in prompts[1]


def test_for_model_gemini_path() -> None:
    prompts = SystemPrompt.for_model(_model("gemini-2.5-pro", provider_id="google"))
    assert len(prompts) >= 2
    assert "Gemini family" in prompts[1]


def test_for_model_claude_path() -> None:
    prompts = SystemPrompt.for_model(_model("claude-sonnet-4", provider_id="anthropic", api_type="anthropic"))
    assert len(prompts) >= 2
    assert "Claude family" in prompts[1]
