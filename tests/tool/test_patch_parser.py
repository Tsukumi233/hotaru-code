import pytest

from hotaru.patch import UpdateHunk, derive_new_contents_from_chunks, parse_patch


def test_parse_patch_update_hunk() -> None:
    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: sample.txt",
            "@@",
            "-hello",
            "+hello world",
            "*** End Patch",
        ]
    )
    hunks = parse_patch(patch)
    assert len(hunks) == 1
    assert isinstance(hunks[0], UpdateHunk)
    assert hunks[0].path == "sample.txt"
    assert hunks[0].chunks[0].old_lines == ["hello"]
    assert hunks[0].chunks[0].new_lines == ["hello world"]


def test_derive_new_contents_from_chunks() -> None:
    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: sample.txt",
            "@@",
            "-hello",
            "+hello world",
            "*** End Patch",
        ]
    )
    hunks = parse_patch(patch)
    hunk = hunks[0]
    assert isinstance(hunk, UpdateHunk)

    new_text = derive_new_contents_from_chunks("sample.txt", hunk.chunks, "hello\n")
    assert new_text == "hello world\n"

