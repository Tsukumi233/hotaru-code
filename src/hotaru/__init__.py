"""Hotaru Code - AI-powered coding assistant.

A Python translation of OpenCode, providing AI agent capabilities
for software development tasks.
"""

__version__ = "0.1.0"

# Lazy imports to avoid circular dependencies
def __getattr__(name: str):
    """Lazy import module components."""
    if name in ("GlobalPath", "Identifier", "Bus", "BusEvent", "Context", "Log"):
        from . import core
        return getattr(core, name)
    if name in ("Project", "Instance", "State"):
        from . import project
        return getattr(project, name)
    if name in ("Provider", "ModelsDev"):
        from . import provider
        return getattr(provider, name)
    if name in ("Agent", "AgentInfo"):
        from . import agent
        return getattr(agent, name)
    if name in ("Session", "Message", "MessageInfo"):
        from . import session
        return getattr(session, name)
    if name == "Permission":
        from . import permission
        return permission.Permission
    if name in ("Tool", "ToolContext", "ToolResult"):
        from . import tool
        return getattr(tool, name)
    if name in ("Skill",):
        from . import skill
        return getattr(skill, name)
    if name in ("Server", "ServerInfo"):
        from . import server
        return getattr(server, name)
    if name in ("MCP", "MCPStatus", "MCPResource"):
        from . import mcp
        return getattr(mcp, name)
    if name in ("LSP", "LSPStatus"):
        from . import lsp
        return getattr(lsp, name)
    if name in ("TuiApp", "run_tui", "TuiEvent"):
        from . import tui
        return getattr(tui, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Version
    "__version__",
    # Core
    "GlobalPath",
    "Identifier",
    "Bus",
    "BusEvent",
    "Context",
    "Log",
    # Project
    "Project",
    "Instance",
    "State",
    # Provider
    "Provider",
    "ModelsDev",
    # Agent
    "Agent",
    "AgentInfo",
    # Session
    "Session",
    "Message",
    "MessageInfo",
    # Permission
    "Permission",
    # Tool
    "Tool",
    "ToolContext",
    "ToolResult",
    # Skill
    "Skill",
    # Server
    "Server",
    "ServerInfo",
    # MCP
    "MCP",
    "MCPStatus",
    "MCPResource",
    # LSP
    "LSP",
    "LSPStatus",
    # TUI
    "TuiApp",
    "run_tui",
    "TuiEvent",
]
