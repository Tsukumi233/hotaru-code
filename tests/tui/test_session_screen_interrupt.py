from hotaru.tui.screens import SessionScreen


def test_escape_mode_routes_home_when_not_busy(monkeypatch) -> None:
    screen = SessionScreen(session_id="session_1")
    monkeypatch.setattr(screen, "_is_busy", lambda: False)
    assert screen._escape_mode(now=1.0) == "home"


def test_escape_mode_arms_then_interrupts_within_window(monkeypatch) -> None:
    screen = SessionScreen(session_id="session_1")
    monkeypatch.setattr(screen, "_is_busy", lambda: True)

    assert screen._escape_mode(now=1.0) == "armed"
    assert screen._escape_mode(now=2.0) == "interrupt"
    assert screen._interrupt_pending is True


def test_escape_mode_rearms_after_window_expires(monkeypatch) -> None:
    screen = SessionScreen(session_id="session_1")
    monkeypatch.setattr(screen, "_is_busy", lambda: True)

    assert screen._escape_mode(now=1.0) == "armed"
    assert screen._escape_mode(now=7.0) == "armed"


def test_escape_mode_blocks_repeat_when_interrupt_pending(monkeypatch) -> None:
    screen = SessionScreen(session_id="session_1")
    screen._interrupt_pending = True
    monkeypatch.setattr(screen, "_is_busy", lambda: True)

    assert screen._escape_mode(now=2.0) == "pending"
