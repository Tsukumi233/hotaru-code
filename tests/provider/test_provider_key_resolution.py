from hotaru.core.config import ProviderConfig
from hotaru.provider.auth import ProviderAuth
from hotaru.provider.provider import _create_custom_provider


def test_custom_provider_prefers_auth_store_key(monkeypatch) -> None:
    monkeypatch.setattr(ProviderAuth, "get", classmethod(lambda cls, provider_id: "auth-key"))

    config = ProviderConfig.model_validate(
        {
            "type": "openai",
            "name": "Demo",
            "options": {"baseURL": "https://api.example.com/v1", "apiKey": "config-key"},
            "models": {"demo-model": {"name": "Demo Model"}},
        }
    )

    provider = _create_custom_provider("demo", config)
    assert provider is not None
    assert provider.key == "auth-key"


def test_custom_provider_uses_config_key_when_auth_missing(monkeypatch) -> None:
    monkeypatch.setattr(ProviderAuth, "get", classmethod(lambda cls, provider_id: None))

    config = ProviderConfig.model_validate(
        {
            "type": "anthropic",
            "name": "Demo",
            "options": {"baseURL": "https://api.example.com/v1", "apiKey": "config-key"},
            "models": {"demo-model": {"name": "Demo Model"}},
        }
    )

    provider = _create_custom_provider("demo", config)
    assert provider is not None
    assert provider.key == "config-key"
