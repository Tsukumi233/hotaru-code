"""Provider registry and model loading.

Manages AI provider configuration, authentication, and model access.
"""

import os
from enum import Enum
from typing import Any, Callable, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from ..core.config import ConfigManager, ProviderConfig
from ..util.log import Log
from .auth import ProviderAuth
from .transform import ProviderTransform
from .models import (
    ModelCapabilities,
    ModelCost,
    ModelInfo,
    ModelLimit,
    ModelsDev,
    ProviderDef,
)

log = Log.create({"service": "provider"})

DEFAULT_CONTEXT_LIMIT = 128000
DEFAULT_OUTPUT_LIMIT = ProviderTransform.OUTPUT_TOKEN_MAX


class ProviderSource(str, Enum):
    """Source of provider configuration."""
    ENV = "env"
    CONFIG = "config"
    CUSTOM = "custom"
    API = "api"


class ModelCostInfo(BaseModel):
    """Processed model cost information."""
    input: float = 0
    output: float = 0
    cache_read: float = 0
    cache_write: float = 0


class ProcessedModelInfo(BaseModel):
    """Fully processed model information."""
    id: str
    provider_id: str
    name: str
    family: Optional[str] = None
    api_id: str
    api_url: Optional[str] = None
    api_type: Literal["openai", "anthropic"] = "openai"

    status: Literal["alpha", "beta", "deprecated", "active"] = "active"
    release_date: str = ""

    capabilities: ModelCapabilities = Field(default_factory=ModelCapabilities)
    cost: ModelCostInfo = Field(default_factory=ModelCostInfo)
    limit: ModelLimit = Field(
        default_factory=lambda: ModelLimit(
            context=DEFAULT_CONTEXT_LIMIT,
            output=DEFAULT_OUTPUT_LIMIT,
        )
    )

    options: Dict[str, Any] = Field(default_factory=dict)
    headers: Dict[str, str] = Field(default_factory=dict)
    variants: Dict[str, Dict[str, Any]] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")


class ProviderInfo(BaseModel):
    """Provider information."""
    id: str
    name: str
    source: ProviderSource = ProviderSource.CUSTOM
    env: List[str] = []
    key: Optional[str] = None
    options: Dict[str, Any] = Field(default_factory=dict)
    models: Dict[str, ProcessedModelInfo] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")


class ModelNotFoundError(Exception):
    """Raised when a model is not found."""

    def __init__(
        self,
        provider_id: str,
        model_id: str,
        suggestions: Optional[List[str]] = None
    ):
        self.provider_id = provider_id
        self.model_id = model_id
        self.suggestions = suggestions or []
        msg = f"Model '{model_id}' not found for provider '{provider_id}'"
        if suggestions:
            msg += f". Did you mean: {', '.join(suggestions)}?"
        super().__init__(msg)


class ProviderInitError(Exception):
    """Raised when provider initialization fails."""

    def __init__(self, provider_id: str, cause: Optional[Exception] = None):
        self.provider_id = provider_id
        self.cause = cause
        super().__init__(f"Failed to initialize provider '{provider_id}'")


def _process_model(provider: ProviderDef, model: ModelInfo) -> ProcessedModelInfo:
    """Convert ModelInfo to ProcessedModelInfo."""
    capabilities = ModelCapabilities(
        temperature=model.temperature,
        reasoning=model.reasoning,
        attachment=model.attachment,
        toolcall=model.tool_call,
        input={
            "text": "text" in (model.modalities.input if model.modalities else []),
            "audio": "audio" in (model.modalities.input if model.modalities else []),
            "image": "image" in (model.modalities.input if model.modalities else []),
            "video": "video" in (model.modalities.input if model.modalities else []),
            "pdf": "pdf" in (model.modalities.input if model.modalities else []),
        } if model.modalities else {"text": True, "audio": False, "image": False, "video": False, "pdf": False},
        output={
            "text": "text" in (model.modalities.output if model.modalities else []),
            "audio": "audio" in (model.modalities.output if model.modalities else []),
            "image": "image" in (model.modalities.output if model.modalities else []),
            "video": "video" in (model.modalities.output if model.modalities else []),
            "pdf": "pdf" in (model.modalities.output if model.modalities else []),
        } if model.modalities else {"text": True, "audio": False, "image": False, "video": False, "pdf": False},
        interleaved=model.interleaved or False,
    )

    cost = ModelCostInfo(
        input=model.cost.input if model.cost else 0,
        output=model.cost.output if model.cost else 0,
        cache_read=model.cost.cache_read if model.cost and model.cost.cache_read else 0,
        cache_write=model.cost.cache_write if model.cost and model.cost.cache_write else 0,
    )

    # Determine API type from provider ID
    api_type = "anthropic" if provider.id == "anthropic" else "openai"

    processed = ProcessedModelInfo(
        id=model.id,
        provider_id=provider.id,
        name=model.name,
        family=model.family,
        api_id=model.id,
        api_url=provider.api,
        api_type=api_type,
        status=model.status or "active",
        release_date=model.release_date,
        capabilities=capabilities,
        cost=cost,
        limit=model.limit,
        options=model.options or {},
        headers=model.headers or {},
        variants=model.variants or {},
    )
    generated_variants = ProviderTransform.variants(processed)
    if generated_variants:
        merged = dict(generated_variants)
        merged.update(processed.variants)
        processed.variants = merged
    return processed


def _process_provider(provider_def: ProviderDef) -> ProviderInfo:
    """Convert ProviderDef to ProviderInfo."""
    models = {
        model_id: _process_model(provider_def, model)
        for model_id, model in provider_def.models.items()
    }

    return ProviderInfo(
        id=provider_def.id,
        name=provider_def.name,
        source=ProviderSource.CUSTOM,
        env=provider_def.env,
        options={},
        models=models,
    )


def _lookup_interleaved(model_id: str) -> Optional[Union[bool, dict]]:
    """Best-effort lookup of interleaved capability from models.dev cache."""
    cache = ModelsDev._cache
    if not cache:
        return None
    for provider_def in cache.values():
        model_info = provider_def.models.get(model_id)
        if model_info and model_info.interleaved:
            val = model_info.interleaved
            if hasattr(val, "model_dump"):
                return val.model_dump()
            return val
    return None


def _create_custom_provider(provider_id: str, config: ProviderConfig) -> Optional[ProviderInfo]:
    """Create a custom provider from config.

    Args:
        provider_id: Provider ID
        config: Provider configuration

    Returns:
        ProviderInfo or None if invalid
    """
    if not config.models:
        log.warn("custom provider has no models", {"provider_id": provider_id})
        return None

    options = config.options or {}
    base_url = options.get("baseURL")
    headers = options.get("headers", {})

    # Determine provider type: "openai" (default) or "anthropic"
    provider_type = config.type or "openai"

    # Create models
    models: Dict[str, ProcessedModelInfo] = {}
    for model_id, model_config in config.models.items():
        model_name = model_config.name if model_config else model_id
        model_limit = model_config.limit if model_config else None
        model_options = model_config.options if model_config else {}
        model_headers = model_config.headers if model_config else {}

        # Read interleaved from model config, fall back to models.dev lookup
        raw_interleaved = getattr(model_config, "interleaved", None) if model_config else None
        if raw_interleaved is None:
            raw_interleaved = _lookup_interleaved(model_id)

        from .models import InterleavedConfig
        if isinstance(raw_interleaved, dict):
            try:
                interleaved_val: Union[bool, InterleavedConfig] = InterleavedConfig.model_validate(raw_interleaved)
            except Exception:
                interleaved_val = False
        elif isinstance(raw_interleaved, InterleavedConfig):
            interleaved_val = raw_interleaved
        elif raw_interleaved is True:
            interleaved_val = True
        else:
            interleaved_val = False

        processed = ProcessedModelInfo(
            id=model_id,
            provider_id=provider_id,
            name=model_name or model_id,
            api_id=model_id,
            api_url=base_url,
            api_type=provider_type,
            status="active",
            capabilities=ModelCapabilities(
                temperature=True,
                reasoning=False,
                attachment=False,
                toolcall=True,
                input={"text": True, "audio": False, "image": False, "video": False, "pdf": False},
                output={"text": True, "audio": False, "image": False, "video": False, "pdf": False},
                interleaved=interleaved_val,
            ),
            cost=ModelCostInfo(),
            limit=ModelLimit(
                context=model_limit.get("context", DEFAULT_CONTEXT_LIMIT) if model_limit else DEFAULT_CONTEXT_LIMIT,
                output=model_limit.get("output", DEFAULT_OUTPUT_LIMIT) if model_limit else DEFAULT_OUTPUT_LIMIT,
            ),
            options=model_options or {},
            headers={**headers, **(model_headers or {})},
        )
        generated_variants = ProviderTransform.variants(processed)
        if generated_variants:
            merged = dict(generated_variants)
            merged.update(processed.variants)
            processed.variants = merged
        models[model_id] = processed

    # Determine env var name for API key
    env_var = f"{provider_id.upper().replace('-', '_')}_API_KEY"
    resolved_key = _resolve_provider_key(provider_id, [env_var], options)

    return ProviderInfo(
        id=provider_id,
        name=config.name or provider_id,
        source=ProviderSource.CONFIG,
        env=[env_var],
        key=resolved_key,
        options={**options, "type": provider_type},
        models=models,
    )


def _resolve_provider_key(
    provider_id: str,
    env_vars: List[str],
    options: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Resolve an API key from auth store, config, or environment."""
    stored_key = ProviderAuth.get(provider_id)
    if stored_key:
        return stored_key

    if options:
        configured_key = options.get("apiKey")
        if isinstance(configured_key, str) and configured_key:
            return configured_key

    for env_var in env_vars:
        api_key = os.environ.get(env_var)
        if api_key:
            return api_key

    return None


def _apply_provider_config(
    provider: ProviderInfo,
    *,
    provider_id: str,
    config: ProviderConfig,
) -> ProviderInfo:
    options = config.options or {}
    if options:
        provider.options.update(options)
        base_url = options.get("baseURL")
        if base_url:
            for model in provider.models.values():
                model.api_url = base_url
    provider.key = _resolve_provider_key(provider_id, provider.env, provider.options)
    provider.source = ProviderSource.CONFIG
    return provider


class Provider:
    """Provider registry.

    Manages AI provider discovery, configuration, and model access.
    Supports multiple provider sources: environment variables, config files,
    and API keys.
    """

    _providers: Optional[Dict[str, ProviderInfo]] = None
    _initialized: bool = False

    @classmethod
    async def _initialize(cls) -> Dict[str, ProviderInfo]:
        """Initialize providers from all sources."""
        if cls._providers is not None:
            return cls._providers

        log.info("initializing providers")
        providers: Dict[str, ProviderInfo] = {}

        # Load from models.dev
        models_dev = await ModelsDev.get()
        database = {
            provider_id: _process_provider(provider_def)
            for provider_id, provider_def in models_dev.items()
        }

        # Load config
        config = await ConfigManager.get()
        disabled = set(config.disabled_providers or [])
        enabled = set(config.enabled_providers) if config.enabled_providers else None
        configured = set(config.provider.keys()) if config.provider else set()
        config_only = bool(configured)

        def is_allowed(provider_id: str) -> bool:
            if enabled and provider_id not in enabled:
                return False
            if provider_id in disabled:
                return False
            return True

        # Load built-in providers with keys from auth/config/env
        for provider_id, provider in database.items():
            if not is_allowed(provider_id):
                continue

            provider = provider.model_copy()
            provider_config = config.provider.get(provider_id) if config.provider else None
            if config_only and not provider_config:
                continue
            if provider_config:
                provider = _apply_provider_config(
                    provider,
                    provider_id=provider_id,
                    config=provider_config,
                )

            if not provider_config:
                provider.key = _resolve_provider_key(provider_id, provider.env, provider.options)
                if provider.key:
                    provider.source = ProviderSource.ENV

            if provider.key or provider_config:
                providers[provider_id] = provider

        # Apply config overrides and add custom providers
        if config.provider:
            for provider_id, provider_config in config.provider.items():
                if not is_allowed(provider_id):
                    continue

                # Check if this is a custom provider definition
                # Custom if: has type field, or has models and not in database
                is_custom = provider_config.type or (provider_config.models and provider_id not in database)
                if is_custom:
                    # Create custom provider
                    custom_provider = _create_custom_provider(provider_id, provider_config)
                    if custom_provider:
                        providers[provider_id] = custom_provider
                        log.info("added custom provider", {"provider_id": provider_id})
                elif provider_id in providers:
                    # Merge config into existing provider
                    providers[provider_id] = _apply_provider_config(
                        providers[provider_id],
                        provider_id=provider_id,
                        config=provider_config,
                    )
                elif provider_id in database:
                    # Add provider from database with config
                    providers[provider_id] = _apply_provider_config(
                        database[provider_id].model_copy(),
                        provider_id=provider_id,
                        config=provider_config,
                    )

        # Filter deprecated models
        for provider in providers.values():
            to_remove = []
            for model_id, model in provider.models.items():
                if model.status == "deprecated":
                    to_remove.append(model_id)
            for model_id in to_remove:
                del provider.models[model_id]

        # Remove providers with no models
        empty_providers = [
            provider_id
            for provider_id, provider in providers.items()
            if not provider.models
        ]
        for provider_id in empty_providers:
            del providers[provider_id]

        for provider_id in providers:
            log.info("found provider", {"provider_id": provider_id})

        cls._providers = providers
        cls._initialized = True
        return providers

    @classmethod
    async def list(cls) -> Dict[str, ProviderInfo]:
        """List all available providers.

        Returns:
            Dictionary of provider ID to ProviderInfo
        """
        return await cls._initialize()

    @classmethod
    async def get(cls, provider_id: str) -> Optional[ProviderInfo]:
        """Get a specific provider.

        Args:
            provider_id: Provider ID

        Returns:
            ProviderInfo or None if not found
        """
        providers = await cls._initialize()
        return providers.get(provider_id)

    @classmethod
    async def get_model(
        cls,
        provider_id: str,
        model_id: str
    ) -> ProcessedModelInfo:
        """Get a specific model.

        Args:
            provider_id: Provider ID
            model_id: Model ID

        Returns:
            ProcessedModelInfo

        Raises:
            ModelNotFoundError: If model is not found
        """
        providers = await cls._initialize()

        provider = providers.get(provider_id)
        if not provider:
            available = list(providers.keys())
            # Simple fuzzy matching
            suggestions = [p for p in available if provider_id.lower() in p.lower()][:3]
            raise ModelNotFoundError(provider_id, model_id, suggestions)

        model = provider.models.get(model_id)
        if not model:
            available = list(provider.models.keys())
            suggestions = [m for m in available if model_id.lower() in m.lower()][:3]
            raise ModelNotFoundError(provider_id, model_id, suggestions)

        return model

    @classmethod
    def parse_model(cls, model_string: str) -> tuple[str, str]:
        """Parse a model string into provider and model ID.

        Args:
            model_string: Model string in format "provider/model"

        Returns:
            Tuple of (provider_id, model_id)
        """
        parts = model_string.split("/", 1)
        if len(parts) == 1:
            return parts[0], parts[0]
        return parts[0], parts[1]

    @classmethod
    async def default_model(cls) -> tuple[str, str]:
        """Get the default model.

        Returns:
            Tuple of (provider_id, model_id)
        """
        config = await ConfigManager.get()

        if config.model:
            return cls.parse_model(config.model)

        providers = await cls.list()
        if not providers:
            raise RuntimeError("No providers available")

        # Priority list for default model selection
        priority = ["claude-sonnet-4", "gpt-4", "gemini-pro"]

        for provider in providers.values():
            for prio in priority:
                for model_id, model in provider.models.items():
                    if prio in model_id:
                        return provider.id, model_id

        # Fall back to first available model
        provider = next(iter(providers.values()))
        model_id = next(iter(provider.models.keys()))
        return provider.id, model_id

    @classmethod
    async def get_small_model(cls, provider_id: str) -> Optional[ProcessedModelInfo]:
        """Get a small/fast model for a provider.

        Args:
            provider_id: Provider ID

        Returns:
            ProcessedModelInfo or None
        """
        config = await ConfigManager.get()

        if config.small_model:
            pid, mid = cls.parse_model(config.small_model)
            try:
                return await cls.get_model(pid, mid)
            except ModelNotFoundError:
                pass

        provider = await cls.get(provider_id)
        if not provider:
            return None

        # Priority for small models
        priority = [
            "haiku",
            "flash",
            "mini",
            "nano",
            "small",
        ]

        for prio in priority:
            for model_id, model in provider.models.items():
                if prio in model_id.lower():
                    return model

        return None

    @classmethod
    def reset(cls) -> None:
        """Reset the provider cache."""
        cls._providers = None
        cls._initialized = False
