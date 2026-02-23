from pathlib import Path

import pytest

from hotaru.tool.list import ListParams, LsTool, list_execute
from hotaru.tool.registry import ToolRegistry
from hotaru.tool.tool import ToolContext
from tests.helpers import fake_app


@pytest.mark.anyio
async def test_list_tool_requests_list_permission_and_ignores_common_dirs(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "index.js").write_text("module.exports = {}\n", encoding="utf-8")

    ctx = ToolContext(
        app=fake_app(),
        session_id="session_test",
        message_id="message_test",
        agent="build",
        extra={"cwd": str(tmp_path), "worktree": str(tmp_path)},
    )
    specs = await LsTool.permissions(ListParams(path=str(tmp_path)), ctx)

    result = await list_execute(ListParams(path=str(tmp_path)), ctx)

    assert len(specs) == 1
    assert specs[0].permission == "list"
    assert specs[0].patterns == [str(tmp_path.resolve())]
    assert specs[0].always == ["*"]
    assert "src/" in result.output
    assert "main.py" in result.output
    assert "node_modules/" not in result.output


def test_list_tool_is_registered() -> None:
    registry = ToolRegistry()
    assert "ls" in registry.ids()
