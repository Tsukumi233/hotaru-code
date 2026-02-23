import asyncio

import pytest

from hotaru.core.config import Config, ConfigManager
from hotaru.mcp.mcp import MCP, MCPState


@pytest.mark.anyio
async def test_init_clients_runs_sequentially(monkeypatch: pytest.MonkeyPatch) -> None:
    config = Config.model_validate(
        {
            "mcp": {
                "one": {"type": "local", "command": ["echo"]},
                "two": {"type": "local", "command": ["echo"]},
                "three": {"type": "local", "command": ["echo"]},
            }
        }
    )

    async def fake_get(cls):
        return config

    mcp = MCP()
    mcp._state = MCPState()
    monkeypatch.setattr(ConfigManager, "get", classmethod(fake_get))

    active = 0
    max_active = 0
    order: list[str] = []

    async def fake_init_single_client(self, name: str, cfg_dict):
        nonlocal active, max_active
        order.append(f"start:{name}")
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0)
        order.append(f"end:{name}")
        active -= 1

    monkeypatch.setattr(MCP, "_init_single_client", fake_init_single_client)

    await mcp._init_clients()

    assert max_active == 1
    assert order == [
        "start:one",
        "end:one",
        "start:two",
        "end:two",
        "start:three",
        "end:three",
    ]
