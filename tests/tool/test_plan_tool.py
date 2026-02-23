import pytest
from types import SimpleNamespace

from hotaru.question.question import RejectedError as QuestionRejectedError
from hotaru.session.session import SessionInfo, SessionTime
from hotaru.tool.plan import PlanParams, plan_enter_execute, plan_exit_execute
from hotaru.tool.tool import ToolContext
from tests.helpers import fake_app


def _session_info() -> SessionInfo:
    return SessionInfo(
        id="ses_plan",
        slug="ses_plan",
        project_id="proj",
        agent="build",
        directory="/tmp/project",
        time=SessionTime(created=123, updated=123),
    )


@pytest.mark.anyio
async def test_plan_enter_switches_to_plan_and_returns_mode_switch_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    updates: list[str] = []

    async def fake_get(cls, session_id: str, project_id=None):  # type: ignore[no-untyped-def]
        return _session_info()

    async def fake_update(cls, session_id: str, project_id=None, **kwargs):  # type: ignore[no-untyped-def]
        updates.append(kwargs.get("agent"))
        return _session_info()

    async def fake_ask(**kwargs):  # type: ignore[no-untyped-def]
        return [["Yes"]]

    monkeypatch.setattr("hotaru.session.session.Session.get", classmethod(fake_get))
    monkeypatch.setattr("hotaru.session.session.Session.update", classmethod(fake_update))
    app = fake_app(question=SimpleNamespace(ask=fake_ask))

    result = await plan_enter_execute(
        PlanParams(),
        ToolContext(
            session_id="ses_plan",
            message_id="msg_1",
            agent="build",
            call_id="call_1",
            extra={"worktree": "/tmp/project"},
            app=app,
        ),
    )

    assert updates == ["plan"]
    assert result.metadata["mode_switch"]["to"] == "plan"
    assert result.metadata["synthetic_user"]["agent"] == "plan"
    assert "Switching to plan agent" == result.title


@pytest.mark.anyio
async def test_plan_exit_switches_to_build_and_returns_mode_switch_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    updates: list[str] = []

    async def fake_get(cls, session_id: str, project_id=None):  # type: ignore[no-untyped-def]
        info = _session_info()
        info.agent = "plan"
        return info

    async def fake_update(cls, session_id: str, project_id=None, **kwargs):  # type: ignore[no-untyped-def]
        updates.append(kwargs.get("agent"))
        info = _session_info()
        info.agent = kwargs.get("agent", "plan")
        return info

    async def fake_ask(**kwargs):  # type: ignore[no-untyped-def]
        return [["Yes"]]

    monkeypatch.setattr("hotaru.session.session.Session.get", classmethod(fake_get))
    monkeypatch.setattr("hotaru.session.session.Session.update", classmethod(fake_update))
    app = fake_app(question=SimpleNamespace(ask=fake_ask))

    result = await plan_exit_execute(
        PlanParams(),
        ToolContext(
            session_id="ses_plan",
            message_id="msg_1",
            agent="plan",
            call_id="call_1",
            extra={"worktree": "/tmp/project"},
            app=app,
        ),
    )

    assert updates == ["build"]
    assert result.metadata["mode_switch"]["to"] == "build"
    assert result.metadata["synthetic_user"]["agent"] == "build"
    assert "Switching to build agent" == result.title


@pytest.mark.anyio
async def test_plan_enter_rejects_when_user_declines(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get(cls, session_id: str, project_id=None):  # type: ignore[no-untyped-def]
        return _session_info()

    async def fake_ask(**kwargs):  # type: ignore[no-untyped-def]
        return [["No"]]

    monkeypatch.setattr("hotaru.session.session.Session.get", classmethod(fake_get))
    app = fake_app(question=SimpleNamespace(ask=fake_ask))

    with pytest.raises(QuestionRejectedError):
        await plan_enter_execute(
            PlanParams(),
            ToolContext(
                session_id="ses_plan",
                message_id="msg_1",
                agent="build",
                call_id="call_1",
                extra={"worktree": "/tmp/project"},
                app=app,
            ),
        )
