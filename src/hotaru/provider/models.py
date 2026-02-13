"""Model definitions and models.dev integration.

Fetches and caches model information from models.dev API.
"""

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union

import httpx
from pydantic import BaseModel, Field

from ..core.global_paths import GlobalPath
from ..util.log import Log

log = Log.create({"service": "models.dev"})


class ModelCostTier(BaseModel):
    """Cost information for a pricing tier."""
    input: float
    output: float
    cache_read: Optional[float] = None
    cache_write: Optional[float] = None


class ModelCost(BaseModel):
    """Model cost information."""
    input: float = 0
    output: float = 0
    cache_read: Optional[float] = None
    cache_write: Optional[float] = None
    context_over_200k: Optional[ModelCostTier] = None


class ModelLimit(BaseModel):
    """Model token limits."""
    context: int
    input: Optional[int] = None
    output: int


class ModelModalities(BaseModel):
    """Model input/output modalities."""
    input: List[Literal["text", "audio", "image", "video", "pdf"]] = []
    output: List[Literal["text", "audio", "image", "video", "pdf"]] = []


class InterleavedConfig(BaseModel):
    """Interleaved thinking configuration."""
    field: Literal["reasoning_content", "reasoning_details"]


class ModelInfo(BaseModel):
    """Model information from models.dev."""
    id: str
    name: str
    family: Optional[str] = None
    release_date: str = ""
    attachment: bool = False
    reasoning: bool = False
    temperature: bool = True
    tool_call: bool = True
    interleaved: Optional[Union[bool, InterleavedConfig]] = None
    cost: Optional[ModelCost] = None
    limit: ModelLimit
    modalities: Optional[ModelModalities] = None
    experimental: Optional[bool] = None
    status: Optional[Literal["alpha", "beta", "deprecated"]] = None
    options: Dict[str, Any] = Field(default_factory=dict)
    headers: Optional[Dict[str, str]] = None
    provider: Optional[Dict[str, str]] = None
    variants: Optional[Dict[str, Dict[str, Any]]] = None

    class Config:
        extra = "allow"


class ProviderDef(BaseModel):
    """Provider definition from models.dev."""
    id: str
    name: str
    api: Optional[str] = None
    env: List[str] = []
    npm: Optional[str] = None
    models: Dict[str, ModelInfo] = Field(default_factory=dict)

    class Config:
        extra = "allow"


class ModelCapabilities(BaseModel):
    """Processed model capabilities."""
    temperature: bool = False
    reasoning: bool = False
    attachment: bool = False
    toolcall: bool = True
    input: Dict[str, bool] = Field(default_factory=lambda: {
        "text": True, "audio": False, "image": False, "video": False, "pdf": False
    })
    output: Dict[str, bool] = Field(default_factory=lambda: {
        "text": True, "audio": False, "image": False, "video": False, "pdf": False
    })
    interleaved: Union[bool, InterleavedConfig] = False


class ModelsDev:
    """Interface to models.dev API.

    Provides model definitions for all supported AI providers.
    Caches locally and refreshes periodically.
    """

    _cache: Optional[Dict[str, ProviderDef]] = None
    _cache_path: Optional[Path] = None

    @classmethod
    def _get_cache_path(cls) -> Path:
        """Get the cache file path."""
        if cls._cache_path is None:
            cls._cache_path = Path(GlobalPath.cache()) / "models.json"
        return cls._cache_path

    @classmethod
    def _get_url(cls) -> str:
        """Get the models.dev API URL."""
        return os.environ.get("HOTARU_MODELS_URL", "https://models.dev")

    @classmethod
    async def get(cls) -> Dict[str, ProviderDef]:
        """Get all provider definitions.

        Returns:
            Dictionary of provider ID to ProviderDef
        """
        if cls._cache is not None:
            return cls._cache

        # Try to load from cache file
        cache_path = cls._get_cache_path()
        if cache_path.exists():
            try:
                data = json.loads(cache_path.read_text())
                cls._cache = {
                    k: ProviderDef.model_validate(v)
                    for k, v in data.items()
                }
                return cls._cache
            except Exception as e:
                log.warn("failed to load cached models", {"error": str(e)})

        # Check for bundled snapshot
        snapshot_path = Path(__file__).parent / "models_snapshot.json"
        if snapshot_path.exists():
            try:
                data = json.loads(snapshot_path.read_text())
                cls._cache = {
                    k: ProviderDef.model_validate(v)
                    for k, v in data.items()
                }
                return cls._cache
            except Exception:
                pass

        # Fetch from API if not disabled
        if os.environ.get("HOTARU_DISABLE_MODELS_FETCH"):
            cls._cache = {}
            return cls._cache

        try:
            await cls.refresh()
        except Exception as e:
            log.error("failed to fetch models.dev", {"error": str(e)})
            cls._cache = {}

        return cls._cache or {}

    @classmethod
    async def refresh(cls) -> None:
        """Refresh models from models.dev API."""
        url = f"{cls._get_url()}/api.json"
        cache_path = cls._get_cache_path()

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()

            # Ensure cache directory exists
            cache_path.parent.mkdir(parents=True, exist_ok=True)

            # Write to cache
            cache_path.write_text(json.dumps(data, indent=2))

            # Parse and cache
            cls._cache = {
                k: ProviderDef.model_validate(v)
                for k, v in data.items()
            }

            log.info("refreshed models from models.dev")
        except Exception as e:
            log.error("failed to refresh models", {"error": str(e)})
            raise

    @classmethod
    def reset(cls) -> None:
        """Reset the cache."""
        cls._cache = None


# Background refresh task
_refresh_task: Optional[asyncio.Task] = None


async def _periodic_refresh():
    """Periodically refresh models."""
    while True:
        await asyncio.sleep(60 * 60)  # 1 hour
        try:
            await ModelsDev.refresh()
        except Exception:
            pass


def start_background_refresh():
    """Start background refresh task."""
    global _refresh_task
    if _refresh_task is None and not os.environ.get("HOTARU_DISABLE_MODELS_FETCH"):
        _refresh_task = asyncio.create_task(_periodic_refresh())


def stop_background_refresh():
    """Stop background refresh task."""
    global _refresh_task
    if _refresh_task is not None:
        _refresh_task.cancel()
        _refresh_task = None
