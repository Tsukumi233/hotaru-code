"""Persistent auth storage for provider credentials."""

import json
import os
from pathlib import Path
from typing import Dict, Optional

from ..core.global_paths import GlobalPath


class ProviderAuth:
    """Store API keys outside of user-facing config files."""

    @classmethod
    def _filepath(cls) -> Path:
        return Path(GlobalPath.data()) / "provider-auth.json"

    @classmethod
    def all(cls) -> Dict[str, Dict[str, str]]:
        filepath = cls._filepath()
        if not filepath.exists():
            return {}

        try:
            with open(filepath, "r", encoding="utf-8") as handle:
                data = json.load(handle)
                if isinstance(data, dict):
                    return data
        except (OSError, json.JSONDecodeError):
            pass
        return {}

    @classmethod
    def get(cls, provider_id: str) -> Optional[str]:
        entry = cls.all().get(provider_id)
        if not isinstance(entry, dict):
            return None
        key = entry.get("key")
        if isinstance(key, str) and key:
            return key
        return None

    @classmethod
    def set(cls, provider_id: str, api_key: str) -> None:
        data = cls.all()
        data[provider_id] = {"type": "api", "key": api_key}

        filepath = cls._filepath()
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)

        try:
            os.chmod(filepath, 0o600)
        except (AttributeError, OSError):
            pass

    @classmethod
    def remove(cls, provider_id: str) -> None:
        data = cls.all()
        if provider_id not in data:
            return

        del data[provider_id]

        filepath = cls._filepath()
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)

        try:
            os.chmod(filepath, 0o600)
        except (AttributeError, OSError):
            pass
