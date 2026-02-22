from hotaru.permission.constants import permission_for_tool


def test_permission_for_tool_maps_aliases() -> None:
    assert permission_for_tool("write") == "edit"
    assert permission_for_tool("apply_patch") == "edit"
    assert permission_for_tool("ls") == "list"
    assert permission_for_tool("bash") == "bash"
