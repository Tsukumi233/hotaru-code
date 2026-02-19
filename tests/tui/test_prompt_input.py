import pytest
from textual import events
from textual.app import App, ComposeResult

from hotaru.tui.widgets import PromptInput


class _PromptApp(App[None]):
    def __init__(self) -> None:
        super().__init__()
        self.sent: list[str] = []

    def compose(self) -> ComposeResult:
        yield PromptInput(id="prompt")

    def on_prompt_input_submitted(self, event: PromptInput.Submitted) -> None:
        self.sent.append(event.value)


@pytest.mark.anyio
async def test_submit_keeps_multiline_text() -> None:
    app = _PromptApp()
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInput)
        prompt.value = "line 1\nline 2"
        prompt.action_submit()
        await pilot.pause()

        assert app.sent == ["line 1\nline 2"]
        assert prompt.value == ""


@pytest.mark.anyio
async def test_enter_submits_instead_of_newline() -> None:
    app = _PromptApp()
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInput)
        prompt.value = "hello"
        prompt.on_key(events.Key("enter", None))
        await pilot.pause()

        assert app.sent == ["hello"]
        assert prompt.value == ""


@pytest.mark.anyio
async def test_shift_enter_inserts_newline_without_submit() -> None:
    app = _PromptApp()
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInput)
        prompt.value = "hello"
        prompt.on_key(events.Key("shift+enter", None))
        await pilot.pause()

        assert app.sent == []
        assert prompt.value == "hello\n"


def test_slash_query_rejects_multiline_values() -> None:
    assert PromptInput._slash_query("/help") == "help"
    assert PromptInput._slash_query("/help arg") is None
    assert PromptInput._slash_query("/help\narg") is None


def test_prompt_input_limits_visible_rows_to_eight() -> None:
    assert PromptInput.MAX_LINES == 8
    assert f"max-height: {PromptInput.MAX_LINES + 2};" in PromptInput.DEFAULT_CSS
