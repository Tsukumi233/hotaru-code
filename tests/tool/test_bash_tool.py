from hotaru.tool.bash import _requires_conservative_approval


def test_requires_conservative_approval_for_complex_shell_constructs() -> None:
    assert _requires_conservative_approval("echo $(pwd)")
    assert _requires_conservative_approval("cat <(echo hello)")
    assert _requires_conservative_approval("(cd /tmp && ls)")


def test_simple_commands_do_not_require_conservative_approval() -> None:
    assert not _requires_conservative_approval("git status")
    assert not _requires_conservative_approval("npm run test")
