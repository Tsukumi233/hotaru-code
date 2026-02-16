from hotaru.session.processor import SessionProcessor


def _processor() -> SessionProcessor:
    return SessionProcessor(
        session_id="session_plan",
        model_id="gpt-5",
        provider_id="openai",
        agent="plan",
        cwd="/tmp",
        worktree="/tmp",
    )


def test_plan_mode_reminder_uses_create_plan_message_when_missing() -> None:
    reminder = _processor()._build_plan_mode_reminder(plan_path="/tmp/.hotaru/plans/plan.md", exists=False)
    assert "No plan file exists yet." in reminder
    assert "only use the explore subagent type" in reminder
    assert "Phase 5: Call plan_exit" in reminder
    assert "{plan_info}" not in reminder


def test_plan_mode_reminder_uses_existing_plan_message_when_present() -> None:
    reminder = _processor()._build_plan_mode_reminder(plan_path="/tmp/.hotaru/plans/plan.md", exists=True)
    assert "A plan file already exists at /tmp/.hotaru/plans/plan.md." in reminder
    assert "Launch general agent(s) to design the implementation" in reminder
