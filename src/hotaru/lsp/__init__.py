"""Language Server Protocol (LSP) client implementation.

This module provides LSP client functionality for connecting to language
servers and providing IDE-like features such as diagnostics, hover info,
go-to-definition, and more.

Example:
    from hotaru.lsp import LSP

    # Initialize LSP clients
    await LSP.init()

    # Touch a file to get diagnostics
    await LSP.touch_file("src/main.py")

    # Get diagnostics
    diagnostics = await LSP.diagnostics()

    # Get hover information
    hover = await LSP.hover(file="src/main.py", line=10, character=5)
"""

from .lsp import LSP, LSPStatus, LSPRange, LSPSymbol, LSPDocumentSymbol
from .language import LANGUAGE_EXTENSIONS

__all__ = [
    "LSP",
    "LSPStatus",
    "LSPRange",
    "LSPSymbol",
    "LSPDocumentSymbol",
    "LANGUAGE_EXTENSIONS",
]
