from hotaru.tui.commands import Command, CommandRegistry, create_default_commands


def _build_registry() -> CommandRegistry:
    registry = CommandRegistry()
    for command in create_default_commands():
        registry.register(command)
    return registry


def test_execute_unwired_command_returns_reason() -> None:
    registry = _build_registry()

    executed, reason = registry.execute("session.compact", source="slash")
    assert not executed
    assert reason is not None
    assert "wired" in reason.lower()


def test_search_includes_compact_command() -> None:
    registry = _build_registry()

    results = registry.search("compact")
    ids = [command.id for command in results]
    assert "session.compact" in ids


def test_transcript_commands_are_enabled() -> None:
    registry = _build_registry()

    assert registry.get("session.undo").enabled is True
    assert registry.get("session.redo").enabled is True
    assert registry.get("session.undo").slash_name == "undo"
    assert registry.get("session.redo").slash_name == "redo"
    assert registry.get("session.rename").enabled is True
    assert registry.get("session.copy").enabled is True
    assert registry.get("session.export").enabled is True
    assert registry.get("session.share").enabled is True
    assert registry.get("session.toggle.actions").enabled is True
    assert registry.get("session.toggle.actions").slash_name == "actions"
    assert registry.get("session.toggle.thinking").enabled is True
    assert registry.get("session.toggle.thinking").slash_name == "thinking"
    assert registry.get("session.toggle.assistant_metadata").enabled is True
    assert registry.get("session.toggle.assistant_metadata").slash_name == "assistant-metadata"
    assert registry.get("session.toggle.timestamps").enabled is True
    assert registry.get("session.toggle.timestamps").slash_name == "timestamps"
    assert registry.get("project.init").enabled is True
    assert registry.get("project.init").slash_name == "init"
    assert registry.get("provider.connect").enabled is True


def test_execute_passes_argument_to_callback() -> None:
    registry = CommandRegistry()
    calls = []

    registry.register(
        Command(
            id="session.test",
            title="Test",
            on_select=lambda source=None, argument=None: calls.append((source, argument)),
        )
    )

    executed, reason = registry.execute("session.test", source="slash", argument="value")
    assert executed is True
    assert reason is None
    assert calls == [("slash", "value")]
