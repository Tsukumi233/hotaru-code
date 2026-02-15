"""Provider-specific request transforms."""

from __future__ import annotations

import copy
import json
import re
from typing import Any, Dict, Iterable, List, Optional

_EMPTY_ASSISTANT_PLACEHOLDER = "Done."


def _provider_options_alias(provider_id: str) -> str:
    provider = provider_id.lower()
    if provider in {"openai", "azure"}:
        return "openai"
    if provider in {"anthropic"}:
        return "anthropic"
    if provider in {"amazon-bedrock", "bedrock"}:
        return "bedrock"
    if provider in {"openrouter"}:
        return "openrouter"
    return provider


def _parse_json(input_value: Any) -> Dict[str, Any]:
    if isinstance(input_value, dict):
        return input_value
    if isinstance(input_value, str):
        try:
            parsed = json.loads(input_value)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
    return {}


def normalize_tool_call_id(
    tool_call_id: str,
    *,
    provider_id: str,
    model_id: str,
) -> str:
    """Normalize tool call ids for providers with strict requirements."""
    value = str(tool_call_id or "")
    if not value:
        return value

    provider = provider_id.lower()
    model = model_id.lower()
    if provider == "mistral" or "mistral" in model or "devstral" in model:
        # Mistral requires alphanumeric ids up to 9 chars.
        cleaned = re.sub(r"[^a-zA-Z0-9]", "", value)
        return cleaned[:9].ljust(9, "0")

    if provider == "anthropic" or "claude" in model:
        # Claude rejects some characters in tool ids.
        return re.sub(r"[^a-zA-Z0-9_-]", "_", value)

    return value


def remap_provider_options(
    messages: List[Dict[str, Any]],
    *,
    provider_id: str,
) -> List[Dict[str, Any]]:
    """Remap provider options key from provider id to SDK key when needed."""
    key = _provider_options_alias(provider_id=provider_id)
    out: List[Dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        copied = dict(msg)
        opts = copied.get("provider_options")
        if isinstance(opts, dict) and provider_id in opts and key != provider_id:
            mapped = dict(opts)
            mapped[key] = mapped.pop(provider_id)
            copied["provider_options"] = mapped
        out.append(copied)
    return out


def apply_cache_controls(
    messages: List[Dict[str, Any]],
    *,
    provider_id: str,
) -> List[Dict[str, Any]]:
    """Inject provider cache hints on selected messages."""
    if not messages:
        return []

    out = [dict(msg) for msg in messages if isinstance(msg, dict)]
    heads = [idx for idx, msg in enumerate(out) if msg.get("role") == "system"][:2]
    tails = list(range(max(len(out) - 2, 0), len(out)))
    target_indexes = sorted(set(heads + tails))

    cache_by_provider = {
        "anthropic": {"cacheControl": {"type": "ephemeral"}},
        "openrouter": {"cacheControl": {"type": "ephemeral"}},
        "bedrock": {"cachePoint": {"type": "default"}},
        "openai": {"cache_control": {"type": "ephemeral"}},
    }
    key = _provider_options_alias(provider_id=provider_id)
    cache_opt = cache_by_provider.get(key)
    if not cache_opt:
        return out

    for idx in target_indexes:
        msg = out[idx]
        opts = msg.get("provider_options")
        if not isinstance(opts, dict):
            opts = {}
        provider_opts = opts.get(key)
        if not isinstance(provider_opts, dict):
            provider_opts = {}
        provider_opts.update(cache_opt)
        opts[key] = provider_opts
        msg["provider_options"] = opts
    return out


def normalize_messages(
    messages: Iterable[Dict[str, Any]],
    *,
    provider_id: str,
    model_id: str,
    api_type: str,
) -> List[Dict[str, Any]]:
    """Normalize message payloads before provider-specific conversion."""
    out: List[Dict[str, Any]] = []
    source = [copy.deepcopy(msg) for msg in messages if isinstance(msg, dict)]

    for idx, msg in enumerate(source):
        role = msg.get("role")
        content = msg.get("content")

        if role == "assistant":
            tool_calls = msg.get("tool_calls")
            if isinstance(tool_calls, list):
                cleaned: List[Dict[str, Any]] = []
                for call in tool_calls:
                    if not isinstance(call, dict):
                        continue
                    call_copy = dict(call)
                    call_id = call_copy.get("id")
                    if call_id:
                        call_copy["id"] = normalize_tool_call_id(
                            str(call_id),
                            provider_id=provider_id,
                            model_id=model_id,
                        )
                    cleaned.append(call_copy)
                msg["tool_calls"] = cleaned

        if role == "tool":
            tool_call_id = msg.get("tool_call_id")
            if tool_call_id:
                msg["tool_call_id"] = normalize_tool_call_id(
                    str(tool_call_id),
                    provider_id=provider_id,
                    model_id=model_id,
                )

        if api_type == "anthropic" or provider_id.lower() == "anthropic" or "claude" in model_id.lower():
            if role in {"assistant", "user"} and isinstance(content, str) and not content:
                continue

        out.append(msg)

        # Some OpenAI-compatible Mistral gateways reject tool->user adjacency.
        if role == "tool" and idx + 1 < len(source):
            next_role = source[idx + 1].get("role")
            if next_role == "user" and ("mistral" in provider_id.lower() or "mistral" in model_id.lower()):
                out.append({"role": "assistant", "content": _EMPTY_ASSISTANT_PLACEHOLDER})

    out = remap_provider_options(out, provider_id=provider_id)
    out = apply_cache_controls(out, provider_id=provider_id)
    return out


def anthropic_tools(tools: Optional[List[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
    """Convert OpenAI tool definition format to Anthropic input_schema format."""
    if not tools:
        return None
    converted: List[Dict[str, Any]] = []
    for item in tools:
        fn = item.get("function", {}) if isinstance(item, dict) else {}
        name = fn.get("name")
        if not name:
            continue
        converted.append(
            {
                "name": str(name),
                "description": str(fn.get("description", "")),
                "input_schema": dict(fn.get("parameters") or {"type": "object", "properties": {}}),
            }
        )
    return converted


def anthropic_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert OpenAI-style conversation messages to Anthropic format."""
    out: List[Dict[str, Any]] = []
    for raw in messages:
        if not isinstance(raw, dict):
            continue
        role = raw.get("role")
        content = raw.get("content")

        if role == "system":
            # Anthropic system is sent separately.
            continue

        if role == "tool":
            tool_call_id = raw.get("tool_call_id")
            if not tool_call_id:
                continue
            block = {
                "type": "tool_result",
                "tool_use_id": str(tool_call_id),
                "content": str(content or ""),
                "is_error": False,
            }
            if out and out[-1].get("role") == "user" and isinstance(out[-1].get("content"), list):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
            continue

        if role == "assistant":
            blocks: List[Dict[str, Any]] = []
            if isinstance(content, str) and content:
                blocks.append({"type": "text", "text": content})

            tool_calls = raw.get("tool_calls") or []
            if isinstance(tool_calls, list):
                for call in tool_calls:
                    if not isinstance(call, dict):
                        continue
                    call_id = call.get("id")
                    fn = call.get("function") or {}
                    tool_name = fn.get("name")
                    if not call_id or not tool_name:
                        continue
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": str(call_id),
                            "name": str(tool_name),
                            "input": _parse_json(fn.get("arguments")),
                        }
                    )

            if not blocks:
                # Anthropic rejects empty assistant content.
                continue
            out.append({"role": "assistant", "content": blocks})
            continue

        if role == "user":
            text = str(content or "")
            if not text:
                continue
            out.append({"role": "user", "content": text})
            continue

    return out
