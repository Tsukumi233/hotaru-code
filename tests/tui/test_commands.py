from hotaru.tui.commands import CommandRegistry, create_default_commands


def _build_registry() -> CommandRegistry:
    registry = CommandRegistry()
    for command in create_default_commands():
        registry.register(command)
    return registry


def test_execute_disabled_command_returns_reason() -> None:
    registry = _build_registry()

    executed, reason = registry.execute("session.rename", source="slash")
    assert not executed
    assert reason is not None
    assert "not available" in reason.lower()


def test_search_includes_disabled_commands() -> None:
    registry = _build_registry()

    results = registry.search("rename")
    ids = [command.id for command in results]
    assert "session.rename" in ids


def test_transcript_commands_are_enabled() -> None:
    registry = _build_registry()

    assert registry.get("session.copy").enabled is True
    assert registry.get("session.export").enabled is True
    assert registry.get("session.share").enabled is True
    assert registry.get("provider.connect").enabled is True
