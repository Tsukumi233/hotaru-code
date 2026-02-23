import pytest

from hotaru.core.config import Config, ConfigManager
from hotaru.lsp.lsp import LSP, LSPState


@pytest.mark.anyio
async def test_lsp_init_respects_global_disable(monkeypatch: pytest.MonkeyPatch) -> None:
    lsp = LSP()

    async def fake_get(cls):
        return Config.model_validate({"lsp": False})

    monkeypatch.setattr(ConfigManager, "get", classmethod(fake_get))

    lsp._state = LSPState()
    await lsp._init_servers()

    assert lsp._state is not None
    assert lsp._state.servers == {}


@pytest.mark.anyio
async def test_lsp_init_applies_overrides_and_custom_servers(monkeypatch: pytest.MonkeyPatch) -> None:
    lsp = LSP()

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

    lsp._state = LSPState()
    await lsp._init_servers()

    assert lsp._state is not None
    servers = lsp._state.servers

    assert "typescript" not in servers

    assert "pyright" in servers
    assert servers["pyright"].env.get("RUST_LOG") == "debug"
    assert servers["pyright"].initialization["python"]["analysis"]["typeCheckingMode"] == "strict"

    assert "custom-lsp" in servers
    assert servers["custom-lsp"].extensions == [".custom"]
    assert servers["custom-lsp"].env == {"CUSTOM_FLAG": "1"}
    assert servers["custom-lsp"].initialization == {"foo": "bar"}

    assert "invalid-custom" not in servers
