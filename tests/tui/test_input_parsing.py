from hotaru.tui.input_parsing import (
    enrich_content_with_file_references,
    extract_file_reference_tokens,
    parse_slash_command,
)


def test_parse_slash_command_with_args() -> None:
    parsed = parse_slash_command("/rename sprint planning")
    assert parsed is not None
    assert parsed.trigger == "rename"
    assert parsed.args == "sprint planning"


def test_parse_slash_command_ignores_absolute_paths() -> None:
    assert parse_slash_command("/tmp/project") is None


def test_extract_file_reference_tokens_supports_quoted_and_plain_paths() -> None:
    text = 'review @src/hotaru/tui/app.py, and @"README.md" and @\'docs/spec.md\''
    assert extract_file_reference_tokens(text) == [
        "src/hotaru/tui/app.py",
        "README.md",
        "docs/spec.md",
    ]


def test_enrich_content_with_file_references_appends_file_blocks(tmp_path) -> None:
    target = tmp_path / "note.txt"
    target.write_text("hello", encoding="utf-8")

    content, attached, warnings = enrich_content_with_file_references(
        "check @note.txt",
        cwd=str(tmp_path),
    )

    assert attached == ["note.txt"]
    assert warnings == []
    assert "<attached_file path=\"note.txt\">" in content
    assert "hello" in content


def test_enrich_content_with_file_references_reports_missing_files(tmp_path) -> None:
    content, attached, warnings = enrich_content_with_file_references(
        "check @missing.txt",
        cwd=str(tmp_path),
    )

    assert content == "check @missing.txt"
    assert attached == []
    assert warnings == ["Referenced file not found: missing.txt"]
