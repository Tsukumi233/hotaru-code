import pytest

from hotaru.lsp.server import ALL_SERVERS, lsp_download_disabled


DOC_BUILTINS = {
    "astro",
    "bash",
    "clangd",
    "clojure-lsp",
    "csharp",
    "dart",
    "deno",
    "elixir-ls",
    "eslint",
    "fsharp",
    "gleam",
    "gopls",
    "hls",
    "jdtls",
    "kotlin-ls",
    "lua-ls",
    "nixd",
    "ocaml-lsp",
    "oxlint",
    "php intelephense",
    "prisma",
    "pyright",
    "ruby-lsp",
    "rust",
    "sourcekit-lsp",
    "svelte",
    "terraform",
    "tinymist",
    "typescript",
    "vue",
    "yaml-ls",
    "zls",
}


def test_doc_builtins_are_available() -> None:
    assert DOC_BUILTINS.issubset(set(ALL_SERVERS.keys()))


def test_doc_extensions_for_selected_servers() -> None:
    assert set(ALL_SERVERS["pyright"].extensions) == {".py", ".pyi"}
    assert set(ALL_SERVERS["bash"].extensions) == {".sh", ".bash", ".zsh", ".ksh"}
    assert set(ALL_SERVERS["tinymist"].extensions) == {".typ", ".typc"}
    assert set(ALL_SERVERS["typescript"].extensions) == {
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".mts",
        ".cts",
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("true", True),
        ("1", True),
        ("false", False),
        ("0", False),
        ("", False),
    ],
)
def test_disable_lsp_download_truthy(monkeypatch: pytest.MonkeyPatch, value: str, expected: bool) -> None:
    monkeypatch.setenv("OPENCODE_DISABLE_LSP_DOWNLOAD", value)
    assert lsp_download_disabled() is expected
