from pathlib import Path

import pytest

from hotaru.tool.bash import BashParams, BashTool, _requires_conservative_approval
from hotaru.tool.tool import ToolContext
from tests.helpers import fake_app


def test_requires_conservative_approval_for_complex_shell_constructs() -> None:
    assert _requires_conservative_approval("echo $(pwd)")
    assert _requires_conservative_approval("cat <(echo hello)")
    assert _requires_conservative_approval("(cd /tmp && ls)")


def test_simple_commands_do_not_require_conservative_approval() -> None:
    assert not _requires_conservative_approval("git status")
    assert not _requires_conservative_approval("npm run test")


@pytest.mark.anyio
async def test_bash_tool_exposes_permissions_from_permission_hook(tmp_path: Path) -> None:
    ctx = ToolContext(
        app=fake_app(),
        session_id="ses",
        message_id="msg",
        call_id="call",
        agent="build",
        extra={
            "cwd": str(tmp_path),
            "worktree": str(tmp_path),
        },
    )

    params = BashParams(command="git status", description="Check git status")
    specs = await BashTool.permissions(params, ctx)

    assert len(specs) == 1
    assert specs[0].permission == "bash"
    assert specs[0].patterns == ["git status"]
    assert specs[0].always == ["git status *"]
    assert specs[0].metadata == {
        "command": "git status",
        "description": "Check git status",
    }
