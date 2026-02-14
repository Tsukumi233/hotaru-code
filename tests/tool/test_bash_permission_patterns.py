from pathlib import Path

import pytest

from hotaru.tool.bash import BashParams, bash_execute
from hotaru.tool.tool import ToolContext


def _ctx(tmp_path: Path, requests: list[dict]) -> ToolContext:
    async def fake_ask(*, permission, patterns, always=None, metadata=None):
        requests.append(
            {
                "permission": permission,
                "patterns": patterns,
                "always": always or [],
                "metadata": metadata or {},
            }
        )

    ctx = ToolContext(
        session_id="session_test",
        message_id="message_test",
        agent="build",
        extra={"cwd": str(tmp_path), "worktree": str(tmp_path)},
    )
    ctx.ask = fake_ask  # type: ignore[method-assign]
    return ctx


@pytest.mark.anyio
async def test_bash_permission_uses_prefix_based_always_pattern(tmp_path: Path) -> None:
    requests: list[dict] = []
    ctx = _ctx(tmp_path, requests)

    result = await bash_execute(
        BashParams(command="ls -la", description="List files"),
        ctx,
    )

    assert result.metadata["exit"] == 0
    bash_requests = [item for item in requests if item["permission"] == "bash"]
    assert len(bash_requests) == 1
    assert bash_requests[0]["patterns"] == ["ls -la"]
    assert bash_requests[0]["always"] == ["ls *"]


@pytest.mark.anyio
async def test_bash_cd_only_does_not_request_bash_permission(tmp_path: Path) -> None:
    requests: list[dict] = []
    ctx = _ctx(tmp_path, requests)

    await bash_execute(
        BashParams(command="cd ..", description="Change directory"),
        ctx,
    )

    assert not [item for item in requests if item["permission"] == "bash"]


@pytest.mark.anyio
async def test_bash_external_path_argument_requests_external_directory(
    tmp_path: Path,
) -> None:
    outside_file = tmp_path.parent / "outside_hotaru_test.txt"
    outside_file.write_text("hello\n", encoding="utf-8")

    requests: list[dict] = []
    ctx = _ctx(tmp_path, requests)

    await bash_execute(
        BashParams(command=f"cat {outside_file}", description="Read external file"),
        ctx,
    )

    external_requests = [item for item in requests if item["permission"] == "external_directory"]
    assert external_requests
    expected_glob = str(outside_file.parent.resolve() / "*")
    assert expected_glob in external_requests[0]["patterns"]
