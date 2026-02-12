import pytest

from hotaru.agent.agent import Agent
from hotaru.core.config import Config, ConfigManager
from hotaru.permission import Permission, PermissionAction


def _patch_config(monkeypatch: pytest.MonkeyPatch, config_data):
    config = Config.model_validate(config_data)

    async def fake_get(cls):
        return config

    monkeypatch.setattr(ConfigManager, "get", classmethod(fake_get))


@pytest.mark.anyio
async def test_strict_permissions_enable_edit_and_bash_ask(monkeypatch: pytest.MonkeyPatch) -> None:
    Agent.reset()
    _patch_config(monkeypatch, {"strict_permissions": True})

    agent = await Agent.get("build")
    explore = await Agent.get("explore")
    assert agent is not None
    assert explore is not None

    ruleset = Permission.from_config_list(agent.permission)
    explore_ruleset = Permission.from_config_list(explore.permission)
    edit_rule = Permission.evaluate("edit", "src/main.py", ruleset)
    bash_rule = Permission.evaluate("bash", "git status", ruleset)
    explore_bash_rule = Permission.evaluate("bash", "git status", explore_ruleset)

    assert edit_rule.action == PermissionAction.ASK
    assert bash_rule.action == PermissionAction.ASK
    assert explore_bash_rule.action == PermissionAction.ASK

    Agent.reset()


@pytest.mark.anyio
async def test_strict_permissions_disabled_keeps_default_allow(monkeypatch: pytest.MonkeyPatch) -> None:
    Agent.reset()
    _patch_config(monkeypatch, {"strict_permissions": False})

    agent = await Agent.get("build")
    explore = await Agent.get("explore")
    assert agent is not None
    assert explore is not None

    ruleset = Permission.from_config_list(agent.permission)
    explore_ruleset = Permission.from_config_list(explore.permission)
    edit_rule = Permission.evaluate("edit", "src/main.py", ruleset)
    bash_rule = Permission.evaluate("bash", "git status", ruleset)
    explore_bash_rule = Permission.evaluate("bash", "git status", explore_ruleset)

    assert edit_rule.action == PermissionAction.ALLOW
    assert bash_rule.action == PermissionAction.ALLOW
    assert explore_bash_rule.action == PermissionAction.ALLOW

    Agent.reset()


@pytest.mark.anyio
async def test_user_permission_can_override_strict_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    Agent.reset()
    _patch_config(
        monkeypatch,
        {
            "strict_permissions": True,
            "permission": {
                "bash": "allow",
            },
        },
    )

    agent = await Agent.get("build")
    assert agent is not None

    ruleset = Permission.from_config_list(agent.permission)
    bash_rule = Permission.evaluate("bash", "git status", ruleset)
    edit_rule = Permission.evaluate("edit", "src/main.py", ruleset)

    assert bash_rule.action == PermissionAction.ALLOW
    assert edit_rule.action == PermissionAction.ASK

    Agent.reset()
