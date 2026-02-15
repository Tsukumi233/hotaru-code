import pytest

from hotaru.agent.agent import Agent
from hotaru.core.global_paths import GlobalPath
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


@pytest.mark.anyio
async def test_global_permission_string_is_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    Agent.reset()
    _patch_config(
        monkeypatch,
        {
            "permission": "ask",
        },
    )

    agent = await Agent.get("build")
    assert agent is not None

    ruleset = Permission.from_config_list(agent.permission)
    bash_rule = Permission.evaluate("bash", "git status", ruleset)
    read_rule = Permission.evaluate("read", "/tmp/file.txt", ruleset)

    assert bash_rule.action == PermissionAction.ASK
    assert read_rule.action == PermissionAction.ASK

    Agent.reset()


@pytest.mark.anyio
async def test_default_read_env_rules_deny_sensitive_env_files(monkeypatch: pytest.MonkeyPatch) -> None:
    Agent.reset()
    _patch_config(monkeypatch, {})

    agent = await Agent.get("build")
    assert agent is not None

    ruleset = Permission.from_config_list(agent.permission)
    env_rule = Permission.evaluate("read", "/tmp/.env", ruleset)
    nested_env_rule = Permission.evaluate("read", "/tmp/.env.local", ruleset)
    env_example_rule = Permission.evaluate("read", "/tmp/.env.example", ruleset)

    assert env_rule.action == PermissionAction.DENY
    assert nested_env_rule.action == PermissionAction.DENY
    assert env_example_rule.action == PermissionAction.ALLOW

    Agent.reset()


@pytest.mark.anyio
async def test_plan_mode_permissions_are_aligned(monkeypatch: pytest.MonkeyPatch) -> None:
    Agent.reset()
    _patch_config(monkeypatch, {})

    build = await Agent.get("build")
    plan = await Agent.get("plan")
    assert build is not None
    assert plan is not None

    build_rules = Permission.from_config_list(build.permission)
    plan_rules = Permission.from_config_list(plan.permission)

    assert Permission.evaluate("plan_enter", "*", build_rules).action == PermissionAction.ALLOW
    assert Permission.evaluate("plan_exit", "*", build_rules).action == PermissionAction.DENY

    assert Permission.evaluate("plan_enter", "*", plan_rules).action == PermissionAction.DENY
    assert Permission.evaluate("plan_exit", "*", plan_rules).action == PermissionAction.ALLOW

    normal_edit = Permission.evaluate("edit", "/tmp/project/src/main.py", plan_rules)
    local_plan_edit = Permission.evaluate("edit", "/tmp/project/.hotaru/plans/p.md", plan_rules)
    global_plan_edit = Permission.evaluate(
        "edit",
        f"{GlobalPath.data()}/plans/p.md",
        plan_rules,
    )
    assert normal_edit.action == PermissionAction.DENY
    assert local_plan_edit.action == PermissionAction.ALLOW
    assert global_plan_edit.action == PermissionAction.ALLOW

    Agent.reset()
