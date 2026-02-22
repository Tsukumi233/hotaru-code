from pathlib import Path


def test_tool_implementations_do_not_call_ctx_ask_directly() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "hotaru" / "tool"
    allowed = {"tool.py", "permission_guard.py"}

    offenders: list[str] = []
    for file_path in sorted(root.glob("*.py")):
        if file_path.name in allowed:
            continue
        content = file_path.read_text(encoding="utf-8")
        if "ctx.ask(" in content:
            offenders.append(file_path.name)

    assert offenders == []
