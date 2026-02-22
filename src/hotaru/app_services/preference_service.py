"""Preference application service.

Stores and retrieves shared UI preferences from backend-managed state.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core.global_paths import GlobalPath


def _path() -> Path:
    return Path(GlobalPath.state()) / "model.json"


def _load() -> dict[str, Any]:
    path = _path()
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            return value
    except Exception:
        return {}
    return {}


def _save(data: dict[str, Any]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _normalize_current(data: dict[str, Any]) -> dict[str, Any]:
    current = data.get("current")
    agent = data.get("agent")
    out: dict[str, Any] = {}

    if isinstance(current, dict):
        provider_id = current.get("provider_id")
        model_id = current.get("model_id")
        if isinstance(provider_id, str) and provider_id.strip() and isinstance(model_id, str) and model_id.strip():
            out["provider_id"] = provider_id.strip()
            out["model_id"] = model_id.strip()

    if isinstance(agent, str) and agent.strip():
        out["agent"] = agent.strip()

    return out


def _normalize_recent(recent: Any) -> list[dict[str, str]]:
    if not isinstance(recent, list):
        return []

    out: list[dict[str, str]] = []
    for item in recent:
        if not isinstance(item, dict):
            continue
        provider_id = item.get("provider_id")
        model_id = item.get("model_id")
        if not isinstance(provider_id, str) or not provider_id.strip():
            continue
        if not isinstance(model_id, str) or not model_id.strip():
            continue
        out.append({"provider_id": provider_id.strip(), "model_id": model_id.strip()})
    return out


class PreferenceService:
    """Thin orchestration for backend-shared current preference state."""

    @classmethod
    async def get_current(cls) -> dict[str, Any]:
        return _normalize_current(_load())

    @classmethod
    async def update_current(cls, payload: dict[str, Any]) -> dict[str, Any]:
        data = _load()
        changed = False

        provider_id = payload.get("provider_id")
        model_id = payload.get("model_id")
        has_provider = "provider_id" in payload
        has_model = "model_id" in payload

        if has_provider != has_model:
            raise ValueError("Fields 'provider_id' and 'model_id' must be provided together")

        if has_provider and has_model:
            if not isinstance(provider_id, str) or not provider_id.strip():
                raise ValueError("Field 'provider_id' must be a non-empty string")
            if not isinstance(model_id, str) or not model_id.strip():
                raise ValueError("Field 'model_id' must be a non-empty string")

            provider_id = provider_id.strip()
            model_id = model_id.strip()
            data["current"] = {"provider_id": provider_id, "model_id": model_id}

            recent = [
                item
                for item in _normalize_recent(data.get("recent"))
                if not (item["provider_id"] == provider_id and item["model_id"] == model_id)
            ]
            data["recent"] = [{"provider_id": provider_id, "model_id": model_id}, *recent][:10]
            changed = True

        if "agent" in payload:
            agent = payload.get("agent")
            if agent is None:
                data.pop("agent", None)
                changed = True
            elif isinstance(agent, str):
                if not agent.strip():
                    data.pop("agent", None)
                    changed = True
                else:
                    data["agent"] = agent.strip()
                    changed = True
            else:
                raise ValueError("Field 'agent' must be a string or null")

        if not changed:
            raise ValueError("At least one field must be provided")

        _save(data)
        return _normalize_current(data)
