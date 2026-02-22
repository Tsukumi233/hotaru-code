"""Provider application service."""

from __future__ import annotations

from typing import Any

from ..core.config import ConfigManager, ProviderConfig
from ..provider import Provider
from ..provider.auth import ProviderAuth
from .errors import NotFoundError


def _reject_legacy_fields(payload: dict[str, Any], aliases: dict[str, str]) -> None:
    for legacy_name, canonical_name in aliases.items():
        if legacy_name in payload:
            raise ValueError(
                f"Field '{legacy_name}' is not supported. Use '{canonical_name}' instead."
            )


def _provider_to_dict(provider: Any) -> dict[str, Any]:
    return {
        "id": provider.id,
        "name": provider.name,
        "source": provider.source.value if getattr(provider, "source", None) else None,
        "model_count": len(provider.models),
    }


def _model_to_dict(model: Any) -> dict[str, Any]:
    return {
        "id": model.id,
        "name": model.name,
        "api_id": model.api_id,
        "status": model.status,
    }


class ProviderService:
    """Thin orchestration for provider operations."""

    @classmethod
    async def _reload(cls, cwd: str) -> None:
        ConfigManager.reset()
        Provider.reset()
        await ConfigManager.load(cwd)

    @classmethod
    async def list(cls, cwd: str) -> list[dict[str, Any]]:
        await cls._reload(cwd)
        providers = await Provider.list()
        return [_provider_to_dict(provider) for provider in providers.values()]

    @classmethod
    async def list_models(cls, provider_id: str, cwd: str) -> list[dict[str, Any]]:
        await cls._reload(cwd)
        provider = await Provider.get(provider_id)
        if not provider:
            raise NotFoundError("Provider", provider_id)
        return [_model_to_dict(model) for model in provider.models.values()]

    @classmethod
    async def connect(cls, payload: dict[str, Any]) -> dict[str, Any]:
        _reject_legacy_fields(
            payload,
            {
                "providerID": "provider_id",
                "apiKey": "api_key",
            },
        )
        provider_id = payload.get("provider_id")
        if not isinstance(provider_id, str) or not provider_id.strip():
            raise ValueError("Field 'provider_id' is required")
        provider_id = provider_id.strip().lower()

        api_key = payload.get("api_key")
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("Field 'api_key' is required")

        config_payload = payload.get("config")
        if config_payload is None:
            raise ValueError("Field 'config' is required")
        if not isinstance(config_payload, dict):
            raise ValueError("Field 'config' must be an object")

        config = ProviderConfig.model_validate(config_payload)
        updates = {
            "provider": {
                provider_id: config.model_dump(exclude_none=True, by_alias=True)
            }
        }

        await ConfigManager.update_global(updates)
        ProviderAuth.set(provider_id, api_key.strip())

        Provider.reset()
        connected = await Provider.get(provider_id)

        return {
            "ok": True,
            "provider_id": provider_id,
            "provider": _provider_to_dict(connected) if connected else None,
        }
