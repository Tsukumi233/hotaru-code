"""Helpers for including LSP diagnostics in tool outputs."""

from __future__ import annotations

import os
from typing import Dict, List, Tuple, TYPE_CHECKING

from ..util.log import Log

if TYPE_CHECKING:
    from ..lsp.client import LSPDiagnostic


log = Log.create({"service": "tool.lsp_feedback"})

MAX_DIAGNOSTICS_PER_FILE = 20
MAX_PROJECT_DIAGNOSTICS_FILES = 5


def _normalize_path(path: str) -> str:
    return os.path.normpath(os.path.abspath(path))


async def append_lsp_error_feedback(
    output: str,
    file_path: str,
    include_project_files: bool = False,
) -> Tuple[str, Dict[str, List["LSPDiagnostic"]]]:
    """Append LSP diagnostics to tool output.

    Returns updated output and the diagnostics map. If diagnostics collection
    fails, output is returned unchanged and diagnostics is empty.
    """
    try:
        from ..lsp import LSP

        has_clients = await LSP.has_clients(file_path)
        connected_clients = await LSP.touch_file(file_path, wait_for_diagnostics=True)
        diagnostics = await LSP.diagnostics()
    except Exception as e:
        log.warn("failed to collect LSP diagnostics", {"file": file_path, "error": str(e)})
        output += f"\n\nLSP status: diagnostics unavailable ({e})."
        return output, {}

    normalized_file = _normalize_path(file_path)
    project_diagnostics_count = 0
    saw_target_entry = False

    for diag_file, issues in diagnostics.items():
        if _normalize_path(diag_file) == normalized_file:
            saw_target_entry = True

        errors = [item for item in issues if item.severity == 1]
        if not errors:
            continue

        limited = errors[:MAX_DIAGNOSTICS_PER_FILE]
        suffix = (
            f"\n... and {len(errors) - MAX_DIAGNOSTICS_PER_FILE} more"
            if len(errors) > MAX_DIAGNOSTICS_PER_FILE
            else ""
        )

        if _normalize_path(diag_file) == normalized_file:
            output += (
                f'\n\nLSP errors detected in this file, please fix:\n<diagnostics file="{file_path}">\n'
                + "\n".join(LSP.format_diagnostic(item) for item in limited)
                + f"{suffix}\n</diagnostics>"
            )
            continue

        if not include_project_files or project_diagnostics_count >= MAX_PROJECT_DIAGNOSTICS_FILES:
            continue

        project_diagnostics_count += 1
        output += (
            f'\n\nLSP errors detected in other files:\n<diagnostics file="{diag_file}">\n'
            + "\n".join(LSP.format_diagnostic(item) for item in limited)
            + f"{suffix}\n</diagnostics>"
        )

    if connected_clients == 0 and has_clients:
        output += "\n\nLSP status: failed to start language server for this file."
    elif not has_clients:
        output += "\n\nLSP status: no available server for this file."
    elif not saw_target_entry:
        output += "\n\nLSP status: diagnostics not received in time."

    return output, diagnostics
