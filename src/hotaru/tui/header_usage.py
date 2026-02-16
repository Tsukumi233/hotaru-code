"""Usage helpers for session header token/cost display."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple


@dataclass(frozen=True)
class HeaderUsage:
    """Computed session header usage strings."""

    context_info: str = ""
    cost: str = ""


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _message_info(message: Dict[str, Any]) -> Dict[str, Any]:
    info = message.get("info")
    if isinstance(info, dict):
        return info
    return {}


def _assistant_model(message: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    info = _message_info(message)
    model = info.get("model")
    if isinstance(model, dict):
        provider_id = model.get("provider_id")
        model_id = model.get("model_id")
        if isinstance(provider_id, str) and isinstance(model_id, str):
            return provider_id, model_id

    metadata = message.get("metadata")
    if not isinstance(metadata, dict):
        return None, None
    assistant = metadata.get("assistant")
    if not isinstance(assistant, dict):
        return None, None
    provider_id = assistant.get("provider_id")
    model_id = assistant.get("model_id")
    if isinstance(provider_id, str) and isinstance(model_id, str):
        return provider_id, model_id
    return None, None


def _model_context_limit(
    providers: Sequence[Dict[str, Any]],
    *,
    provider_id: Optional[str],
    model_id: Optional[str],
) -> Optional[int]:
    if not provider_id or not model_id:
        return None
    for provider in providers:
        if not isinstance(provider, dict) or provider.get("id") != provider_id:
            continue
        models = provider.get("models")
        if not isinstance(models, dict):
            return None
        model = models.get(model_id)
        if not isinstance(model, dict):
            return None
        limit = model.get("limit")
        if not isinstance(limit, dict):
            return None
        context = _as_int(limit.get("context"))
        if context > 0:
            return context
        return None
    return None


def compute_session_header_usage(
    *,
    messages: Iterable[Dict[str, Any]],
    providers: Sequence[Dict[str, Any]],
) -> HeaderUsage:
    """Compute token/cost strings for the TUI session header."""
    total_cost = 0.0
    latest_total_tokens = 0
    latest_provider_id: Optional[str] = None
    latest_model_id: Optional[str] = None

    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue

        info = _message_info(message)
        total_cost += _as_float(info.get("cost"))

        tokens = info.get("tokens")
        if not isinstance(tokens, dict):
            continue

        output_tokens = _as_int(tokens.get("output"))
        if output_tokens <= 0:
            continue

        latest_total_tokens = (
            _as_int(tokens.get("input"))
            + output_tokens
            + _as_int(tokens.get("reasoning"))
            + _as_int(tokens.get("cache_read"))
            + _as_int(tokens.get("cache_write"))
        )
        latest_provider_id, latest_model_id = _assistant_model(message)

    context_info = ""
    if latest_total_tokens > 0:
        context_info = f"{latest_total_tokens:,}"
        context_limit = _model_context_limit(
            providers,
            provider_id=latest_provider_id,
            model_id=latest_model_id,
        )
        if context_limit and context_limit > 0:
            context_info = f"{context_info}  {round((latest_total_tokens / context_limit) * 100)}%"

    cost = f"${total_cost:.4f}" if total_cost > 0 else ""
    return HeaderUsage(context_info=context_info, cost=cost)
