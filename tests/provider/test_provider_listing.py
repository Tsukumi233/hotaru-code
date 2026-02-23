from __future__ import annotations

import asyncio

from hotaru.core.config import Config
from hotaru.provider.auth import ProviderAuth
from hotaru.provider.models import ModelsDev, ProviderDef
from hotaru.provider.provider import Provider, ProviderSource


def _models() -> dict[str, ProviderDef]:
    return {
        "openai": ProviderDef.model_validate(
            {
                "id": "openai",
                "name": "OpenAI",
                "env": ["OPENAI_API_KEY"],
                "models": {
                    "gpt-5": {
                        "id": "gpt-5",
                        "name": "GPT-5",
                        "limit": {"context": 128000, "output": 4096},
                    }
                },
            }
        ),
        "moonshot": ProviderDef.model_validate(
            {
                "id": "moonshot",
                "name": "Moonshot",
                "env": ["MOONSHOT_API_KEY"],
                "models": {
                    "kimi-k2.5": {
                        "id": "kimi-k2.5",
                        "name": "Kimi K2.5",
                        "limit": {"context": 128000, "output": 4096},
                    }
                },
            }
        ),
    }


async def _fake_models_dev_get(cls):  # type: ignore[no-untyped-def]
    data = _models()
    ModelsDev._cache = data
    return data


def _cfg_with_provider() -> Config:
    return Config.model_validate(
        {
            "provider": {
                "moonshot": {
                    "type": "openai",
                    "name": "Moonshot",
                    "options": {"baseURL": "https://api.moonshot.cn/v1"},
                    "models": {"kimi-k2.5": {"name": "kimi-k2.5"}},
                },
                "cf": {
                    "type": "openai",
                    "name": "cf",
                    "options": {"baseURL": "https://gateway.example.com/v1"},
                    "models": {"custom/model": {"name": "custom/model"}},
                },
            }
        }
    )


def _cfg_without_provider() -> Config:
    return Config.model_validate({})


def _cfg_builtin_override() -> Config:
    return Config.model_validate(
        {
            "provider": {
                "openai": {
                    "options": {
                        "baseURL": "https://gateway.example.com/v1",
                        "apiKey": "config-openai-key",
                    }
                }
            }
        }
    )


async def _fake_get_with_provider(cls):  # type: ignore[no-untyped-def]
    return _cfg_with_provider()


async def _fake_get_without_provider(cls):  # type: ignore[no-untyped-def]
    return _cfg_without_provider()


async def _fake_get_builtin_override(cls):  # type: ignore[no-untyped-def]
    return _cfg_builtin_override()


def test_provider_list_prefers_configured_providers_over_env(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setattr(ModelsDev, "get", classmethod(_fake_models_dev_get))
    monkeypatch.setattr("hotaru.core.config.ConfigManager.get", classmethod(_fake_get_with_provider))

    Provider.reset()
    providers = asyncio.run(Provider.list())

    assert "moonshot" in providers
    assert "cf" in providers
    assert "openai" not in providers
    assert providers["moonshot"].models["kimi-k2.5"].limit.output == 32000
    assert providers["cf"].models["custom/model"].limit.output == 32000


def test_provider_list_keeps_env_providers_when_config_missing(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setattr(ModelsDev, "get", classmethod(_fake_models_dev_get))
    monkeypatch.setattr("hotaru.core.config.ConfigManager.get", classmethod(_fake_get_without_provider))

    Provider.reset()
    providers = asyncio.run(Provider.list())

    assert "openai" in providers


def test_provider_list_applies_builtin_provider_config_to_models_and_key(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(ProviderAuth, "get", classmethod(lambda cls, provider_id: None))
    monkeypatch.setattr(ModelsDev, "get", classmethod(_fake_models_dev_get))
    monkeypatch.setattr("hotaru.core.config.ConfigManager.get", classmethod(_fake_get_builtin_override))

    Provider.reset()
    providers = asyncio.run(Provider.list())

    openai = providers["openai"]
    assert openai.source == ProviderSource.CONFIG
    assert openai.key == "config-openai-key"
    assert openai.options["baseURL"] == "https://gateway.example.com/v1"
    assert openai.models["gpt-5"].api_url == "https://gateway.example.com/v1"
