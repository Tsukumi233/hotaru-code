"""Permission constants for tool name mapping."""

TOOL_PERMISSION_MAP: dict[str, str] = {
    "edit": "edit",
    "write": "edit",
    "patch": "edit",
    "apply_patch": "edit",
    "multiedit": "edit",
    "ls": "list",
}


def permission_for_tool(tool_name: str) -> str:
    """Return permission namespace for a tool name."""
    return TOOL_PERMISSION_MAP.get(tool_name, tool_name)
