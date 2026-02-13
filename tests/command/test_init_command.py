from hotaru.command import expand_builtin_slash_command, render_init_prompt


def test_render_init_prompt_includes_worktree_and_arguments() -> None:
    prompt = render_init_prompt("/repo/root", "focus on python async style")
    assert "/repo/root" in prompt
    assert "focus on python async style" in prompt


def test_expand_builtin_slash_command_for_init() -> None:
    expanded = expand_builtin_slash_command(
        "/init include monorepo conventions",
        "/workspace/project",
    )
    assert expanded is not None
    assert "AGENTS.md" in expanded
    assert "/workspace/project" in expanded
    assert "include monorepo conventions" in expanded


def test_expand_builtin_slash_command_returns_none_for_unknown() -> None:
    expanded = expand_builtin_slash_command("/unknown test", "/workspace/project")
    assert expanded is None
