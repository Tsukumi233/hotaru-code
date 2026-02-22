import pytest

from hotaru.session.doom_loop import DoomLoopDetector


@pytest.mark.anyio
async def test_doom_loop_detector_only_asks_after_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    async def fake_ask(cls, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(dict(kwargs))

    monkeypatch.setattr("hotaru.permission.permission.Permission.ask", classmethod(fake_ask))

    det = DoomLoopDetector(session_id="ses", threshold=3, window=50)
    rules: list[dict] = []

    await det.check(tool_name="read", tool_input={"path": "a"}, ruleset=rules)
    await det.check(tool_name="read", tool_input={"path": "a"}, ruleset=rules)
    assert calls == []

    await det.check(tool_name="read", tool_input={"path": "a"}, ruleset=rules)
    assert len(calls) == 1
    assert calls[0]["permission"] == "doom_loop"
    assert calls[0]["patterns"] == ["read"]


@pytest.mark.anyio
async def test_doom_loop_detector_ignores_non_identical_sequence(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    async def fake_ask(cls, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(dict(kwargs))

    monkeypatch.setattr("hotaru.permission.permission.Permission.ask", classmethod(fake_ask))

    det = DoomLoopDetector(session_id="ses", threshold=3, window=50)
    rules: list[dict] = []

    await det.check(tool_name="read", tool_input={"path": "a"}, ruleset=rules)
    await det.check(tool_name="read", tool_input={"path": "b"}, ruleset=rules)
    await det.check(tool_name="read", tool_input={"path": "a"}, ruleset=rules)

    assert calls == []
