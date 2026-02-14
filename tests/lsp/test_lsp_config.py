import pytest

from hotaru.core.config import Config, ConfigManager
from hotaru.lsp.lsp import LSP, LSPState
import hotaru.lsp.lsp as lsp_module


@pytest.mark.anyio
async def test_lsp_init_respects_global_disable(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get(cls):
        return Config.model_validate({"lsp": False})

    monkeypatch.setattr(ConfigManager, "get", classmethod(fake_get))

    lsp_module._state = LSPState()
    await LSP._init_servers()

    assert lsp_module._state is not None
    assert lsp_module._state.servers == {}

    lsp_module._state = None


@pytest.mark.anyio
async def test_lsp_init_applies_overrides_and_custom_servers(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get(cls):
        return Config.model_validate(
            {
                "lsp": {
                    "typescript": {"disabled": True},
                    "pyright": {
                        "env": {"RUST_LOG": "debug"},
                        "initialization": {
                            "python": {
                                "analysis": {
                                    "typeCheckingMode": "strict",
                                }
                            }
                        },
                    },
                    "custom-lsp": {
                        "command": ["custom-lsp-server", "--stdio"],
                        "extensions": [".custom"],
                        "env": {"CUSTOM_FLAG": "1"},
                        "initialization": {"foo": "bar"},
                    },
                    "invalid-custom": {
                        "command": ["missing-extensions"],
                    },
                }
            }
        )

    monkeypatch.setattr(ConfigManager, "get", classmethod(fake_get))

    lsp_module._state = LSPState()
    await LSP._init_servers()

    assert lsp_module._state is not None
    servers = lsp_module._state.servers

    assert "typescript" not in servers

    assert "pyright" in servers
    assert servers["pyright"].env.get("RUST_LOG") == "debug"
    assert servers["pyright"].initialization["python"]["analysis"]["typeCheckingMode"] == "strict"

    assert "custom-lsp" in servers
    assert servers["custom-lsp"].extensions == [".custom"]
    assert servers["custom-lsp"].env == {"CUSTOM_FLAG": "1"}
    assert servers["custom-lsp"].initialization == {"foo": "bar"}

    assert "invalid-custom" not in servers

    lsp_module._state = None
