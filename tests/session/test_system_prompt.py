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
    assert len(prompts) == 2
    assert "When doing file search, prefer" in prompts[0]


def test_for_model_gemini_path() -> None:
    prompts = SystemPrompt.for_model(_model("gemini-2.5-pro", provider_id="google"))
    assert len(prompts) == 1
    assert "Primary Workflows" in prompts[0]


def test_for_model_claude_path() -> None:
    prompts = SystemPrompt.for_model(_model("claude-sonnet-4", provider_id="anthropic", api_type="anthropic"))
    assert len(prompts) == 1
    assert "When doing file search, prefer to use the Task tool" in prompts[0]


def test_for_model_qwen_path() -> None:
    prompts = SystemPrompt.for_model(_model("qwen2.5-coder", provider_id="aliyun"))
    assert len(prompts) == 1
    assert "When doing file search, prefer to use the Task tool" in prompts[0]


def test_for_model_fallback_path() -> None:
    prompts = SystemPrompt.for_model(_model("custom-model-1", provider_id="custom"))
    assert len(prompts) == 1
    assert "You are hotaru, an interactive CLI tool" in prompts[0]
