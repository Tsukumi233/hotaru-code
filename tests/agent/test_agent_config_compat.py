import pytest

from hotaru.agent.agent import Agent
from hotaru.core.config import Config, ConfigManager
from hotaru.permission import Permission, PermissionAction
from hotaru.skill import Skill


def _patch_config(monkeypatch: pytest.MonkeyPatch, config_data: dict) -> None:
    config = Config.model_validate(config_data)

    async def fake_get(cls):
        return config

    monkeypatch.setattr(ConfigManager, "get", classmethod(fake_get))


def _agents() -> Agent:
    return Agent(Skill())


@pytest.mark.anyio
async def test_agent_tools_and_steps_are_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    agents = _agents()
    _patch_config(
        monkeypatch,
        {
            "agent": {
                "review": {
                    "description": "Review-only subagent",
                    "mode": "subagent",
                    "tools": {
                        "bash": False,
                        "write": False,
                    },
                    "steps": 4,
                    "reasoningEffort": "high",
                }
            }
        },
    )

    review = await agents.get("review")
    assert review is not None
    ruleset = Permission.from_config_list(review.permission)

    bash_rule = Permission.evaluate("bash", "git status", ruleset)
    edit_rule = Permission.evaluate("edit", "src/main.py", ruleset)

    assert bash_rule.action == PermissionAction.DENY
    assert edit_rule.action == PermissionAction.DENY
    assert review.steps == 4
    assert review.options.get("reasoningEffort") == "high"


@pytest.mark.anyio
async def test_agent_tools_ls_maps_to_list_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    agents = _agents()
    _patch_config(
        monkeypatch,
        {
            "agent": {
                "review": {
                    "description": "Review-only subagent",
                    "mode": "subagent",
                    "tools": {
                        "ls": False,
                    },
                }
            }
        },
    )

    review = await agents.get("review")
    assert review is not None
    ruleset = Permission.from_config_list(review.permission)

    list_rule = Permission.evaluate("list", "src", ruleset)
    assert list_rule.action == PermissionAction.DENY
