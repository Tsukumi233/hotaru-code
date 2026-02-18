from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SDK_FILE = REPO_ROOT / "src/hotaru/tui/context/sdk.py"
APP_FILE = REPO_ROOT / "src/hotaru/tui/app.py"
SYNC_FILE = REPO_ROOT / "src/hotaru/tui/context/sync.py"


def _parse_imports(path: Path) -> tuple[set[str], set[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    symbols: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        if isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
            for alias in node.names:
                symbols.add(alias.name)
    return modules, symbols


def test_sdk_context_has_no_direct_domain_orchestration_imports() -> None:
    modules, symbols = _parse_imports(SDK_FILE)

    banned_symbols = {
        "SessionPrompt",
        "SystemPrompt",
        "ProviderAuth",
        "ConfigManager",
        "Provider",
        "Agent",
        "Session",
    }
    assert not (symbols & banned_symbols)

    banned_module_suffixes = (
        "session",
        "provider",
        "agent",
        "core.config",
        "provider.auth",
    )
    offending_modules = {
        module
        for module in modules
        if module.endswith(banned_module_suffixes)
    }
    assert not offending_modules


def test_tui_app_does_not_import_provider_auth_or_config_manager() -> None:
    modules, symbols = _parse_imports(APP_FILE)
    assert "ConfigManager" not in symbols
    assert "ProviderAuth" not in symbols
    assert not {module for module in modules if module.endswith("session")}


def test_sync_context_has_no_direct_session_or_message_store_imports() -> None:
    modules, _symbols = _parse_imports(SYNC_FILE)
    banned_module_suffixes = (
        "session",
        "session.message_store",
    )
    offending_modules = {
        module
        for module in modules
        if module.endswith(banned_module_suffixes)
    }
    assert not offending_modules
