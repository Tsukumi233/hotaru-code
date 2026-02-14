from pathlib import Path

from hotaru.permission import Permission, PermissionAction


def test_from_config_supports_global_string() -> None:
    rules = Permission.from_config("allow")
    assert len(rules) == 1
    assert rules[0].permission == "*"
    assert rules[0].pattern == "*"
    assert rules[0].action == PermissionAction.ALLOW


def test_from_config_expands_home_patterns() -> None:
    home = str(Path.home())
    rules = Permission.from_config(
        {
            "external_directory": {
                "~/projects/*": "allow",
                "$HOME/tmp/*": "deny",
                "~": "ask",
            }
        }
    )

    patterns = {rule.pattern: rule.action for rule in rules}
    assert patterns[f"{home}/projects/*"] == PermissionAction.ALLOW
    assert patterns[f"{home}/tmp/*"] == PermissionAction.DENY
    assert patterns[home] == PermissionAction.ASK


def test_from_config_list_expands_home_patterns() -> None:
    home = str(Path.home())
    rules = Permission.from_config_list(
        [
            {
                "permission": "external_directory",
                "pattern": "~/sandbox/*",
                "action": "allow",
            }
        ]
    )
    assert rules[0].pattern == f"{home}/sandbox/*"
