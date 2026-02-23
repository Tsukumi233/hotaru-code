import pytest
from types import SimpleNamespace

from hotaru.session.doom_loop import DoomLoopDetector


@pytest.mark.anyio
async def test_doom_loop_detector_only_asks_after_threshold() -> None:
    calls: list[dict] = []

    async def fake_ask(**kwargs):  # type: ignore[no-untyped-def]
        calls.append(dict(kwargs))

    det = DoomLoopDetector(
        permission=SimpleNamespace(ask=fake_ask),
        session_id="ses",
        threshold=3,
        window=50,
    )
    rules: list[dict] = []

    await det.check(tool_name="read", tool_input={"path": "a"}, ruleset=rules)
    await det.check(tool_name="read", tool_input={"path": "a"}, ruleset=rules)
    assert calls == []

    await det.check(tool_name="read", tool_input={"path": "a"}, ruleset=rules)
    assert len(calls) == 1
    assert calls[0]["permission"] == "doom_loop"
    assert calls[0]["patterns"] == ["read"]


@pytest.mark.anyio
async def test_doom_loop_detector_ignores_non_identical_sequence() -> None:
    calls: list[dict] = []

    async def fake_ask(**kwargs):  # type: ignore[no-untyped-def]
        calls.append(dict(kwargs))

    det = DoomLoopDetector(
        permission=SimpleNamespace(ask=fake_ask),
        session_id="ses",
        threshold=3,
        window=50,
    )
    rules: list[dict] = []

    await det.check(tool_name="read", tool_input={"path": "a"}, ruleset=rules)
    await det.check(tool_name="read", tool_input={"path": "b"}, ruleset=rules)
    await det.check(tool_name="read", tool_input={"path": "a"}, ruleset=rules)

    assert calls == []
