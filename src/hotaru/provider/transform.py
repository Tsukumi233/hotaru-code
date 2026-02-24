"""Provider-specific request transforms.

This module centralizes provider/model transform behavior so session code can
remain mostly provider-agnostic.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any, Dict, Iterable, List, Optional

_EMPTY_ASSISTANT_PLACEHOLDER = "Done."
_REASONING_TEXT_FIELD = "reasoning_text"
_TOOL_ERROR = "Tool execution failed"
_INTERRUPTED_TOOL_ERROR = "[Tool execution was interrupted]"
_COMPACTED_TOOL_RESULT = "[Old tool result content cleared]"
_COMPACTION_USER_TEXT = "What did we do so far?"
_SUBTASK_USER_TEXT = "The following tool was executed by the user"


class ProviderTransform:
    """Centralized provider transform pipeline."""

    OUTPUT_TOKEN_MAX = 32000
    DEFAULT_TEMPERATURE: Optional[float] = None
    DEFAULT_TOP_P: Optional[float] = None
    DEFAULT_TOP_K: Optional[int] = None

    @staticmethod
    def sdk_key(*, provider_id: str, api_type: str) -> str:
        provider = str(provider_id or "").lower()
        api = str(api_type or "openai").lower()
        if api == "anthropic" or provider == "anthropic":
            return "anthropic"
        if provider in {"openai", "azure"}:
            return "openai"
        if provider in {"amazon-bedrock", "bedrock"}:
            return "bedrock"
        if provider in {"openrouter"}:
            return "openrouter"
        return provider

    @staticmethod
    def interleaved_field(model: Any) -> Optional[str]:
        capabilities = getattr(model, "capabilities", None)
        interleaved = getattr(capabilities, "interleaved", None)

        if isinstance(interleaved, dict):
            field = interleaved.get("field")
            if isinstance(field, str) and field:
                return field
            return None

        field = getattr(interleaved, "field", None)
        if isinstance(field, str) and field:
            return field
        return None

    @staticmethod
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

    @staticmethod
    def assistant_tool_message(
        *,
        text: str,
        tool_calls: Iterable[Dict[str, Any]],
        reasoning_text: str = "",
    ) -> Dict[str, Any]:
        calls: List[Dict[str, Any]] = []
        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            call_id = str(call.get("id") or "")
            if not call_id:
                continue
            fn = call.get("function")
            if isinstance(fn, dict):
                name = str(fn.get("name") or "")
                arguments = str(fn.get("arguments") or "{}")
            else:
                name = str(call.get("name") or "")
                arguments = json.dumps(call.get("input") or {})
            if not name:
                continue
            calls.append(
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": arguments},
                }
            )

        msg: Dict[str, Any] = {
            "role": "assistant",
            "content": text if text else None,
            "tool_calls": calls,
        }
        if reasoning_text:
            msg[_REASONING_TEXT_FIELD] = reasoning_text
        return msg

    @staticmethod
    def tool_result_message(
        *,
        tool_call_id: str,
        status: str,
        output: Optional[str],
        error: Optional[str],
        compacted: bool = False,
        error_fallback: str = _TOOL_ERROR,
        interrupted_text: str = _INTERRUPTED_TOOL_ERROR,
    ) -> Dict[str, Any]:
        if status == "completed":
            content = _COMPACTED_TOOL_RESULT if compacted else (output or "")
        elif status == "error":
            content = error or error_fallback
        else:
            content = interrupted_text

        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content,
        }

    @classmethod
    def from_structured_messages(
        cls,
        messages: Iterable[Any],
        *,
        interleaved_field: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for msg in messages:
            info = getattr(msg, "info", None)
            role = getattr(info, "role", None)
            parts = list(getattr(msg, "parts", []) or [])

            if role == "user":
                text = "".join(
                    str(getattr(part, "text", ""))
                    for part in parts
                    if str(getattr(part, "type", "")) == "text" and not bool(getattr(part, "ignored", False))
                )
                if any(str(getattr(part, "type", "")) == "compaction" for part in parts):
                    text = f"{text}\n\n{_COMPACTION_USER_TEXT}" if text else _COMPACTION_USER_TEXT
                if any(str(getattr(part, "type", "")) == "subtask" for part in parts):
                    text = f"{text}\n\n{_SUBTASK_USER_TEXT}" if text else _SUBTASK_USER_TEXT
                if text:
                    out.append({"role": "user", "content": text})
                continue

            if role != "assistant":
                continue

            content = "".join(
                str(getattr(part, "text", ""))
                for part in parts
                if str(getattr(part, "type", "")) == "text" and not bool(getattr(part, "ignored", False))
            )
            reasoning_text = "".join(
                str(getattr(part, "text", ""))
                for part in parts
                if str(getattr(part, "type", "")) == "reasoning" and str(getattr(part, "text", ""))
            )

            calls: List[Dict[str, Any]] = []
            results: List[Dict[str, Any]] = []
            for part in parts:
                if str(getattr(part, "type", "")) != "tool":
                    continue
                call_id = str(getattr(part, "call_id", "") or "")
                name = str(getattr(part, "tool", "") or "")
                state = getattr(part, "state", None)
                status = str(getattr(state, "status", "") or "")
                if not call_id or not name or not state:
                    continue
                raw = getattr(state, "raw", "")
                data = getattr(state, "input", {}) or {}
                calls.append(
                    {
                        "id": call_id,
                        "name": name,
                        "input": data,
                        "function": {"name": name, "arguments": raw or json.dumps(data)},
                    }
                )
                compacted = bool(getattr(getattr(state, "time", None), "compacted", None))
                results.append(
                    cls.tool_result_message(
                        tool_call_id=call_id,
                        status=status,
                        output=getattr(state, "output", None),
                        error=getattr(state, "error", None),
                        compacted=compacted,
                        error_fallback="",
                    )
                )

            assistant = cls.assistant_tool_message(
                text=content,
                tool_calls=calls,
                reasoning_text=reasoning_text,
            )
            if interleaved_field and reasoning_text:
                assistant[interleaved_field] = reasoning_text
            if interleaved_field and calls and interleaved_field not in assistant:
                assistant[interleaved_field] = ""
            if assistant.get("content") is None and not calls:
                continue
            out.append(assistant)
            out.extend(results)

        return out

    @staticmethod
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

    @classmethod
    def remap_provider_options(
        cls,
        messages: List[Dict[str, Any]],
        *,
        provider_id: str,
        api_type: str = "openai",
    ) -> List[Dict[str, Any]]:
        """Remap provider options key from provider id to SDK key when needed."""
        key = cls.sdk_key(provider_id=provider_id, api_type=api_type)
        provider = str(provider_id or "")
        out: List[Dict[str, Any]] = []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            copied = dict(msg)
            opts = copied.get("provider_options")
            if isinstance(opts, dict) and provider in opts and key != provider:
                mapped = dict(opts)
                mapped[key] = mapped.pop(provider)
                copied["provider_options"] = mapped
            out.append(copied)
        return out

    @classmethod
    def apply_cache_controls(
        cls,
        messages: List[Dict[str, Any]],
        *,
        provider_id: str,
        api_type: str = "openai",
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
        key = cls.sdk_key(provider_id=provider_id, api_type=api_type)
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

    @classmethod
    def _apply_interleaved_reasoning(
        cls,
        msg: Dict[str, Any],
        *,
        interleaved_field: Optional[str],
    ) -> Dict[str, Any]:
        if not interleaved_field:
            return msg

        if msg.get("role") != "assistant":
            return msg

        out = dict(msg)
        content = out.get("content")

        if isinstance(content, list):
            reasoning_chunks: List[str] = []
            filtered_parts: List[Any] = []

            for part in content:
                if isinstance(part, dict) and str(part.get("type") or "").lower() == "reasoning":
                    text = part.get("text")
                    if isinstance(text, str) and text:
                        reasoning_chunks.append(text)
                    continue
                filtered_parts.append(part)

            if reasoning_chunks:
                existing = out.get(interleaved_field)
                existing_text = str(existing) if isinstance(existing, str) else ""
                out[interleaved_field] = existing_text + "".join(reasoning_chunks)

            if filtered_parts != content:
                out["content"] = filtered_parts

        return out

    @classmethod
    def _apply_reasoning_text(
        cls,
        msg: Dict[str, Any],
        *,
        interleaved_field: Optional[str],
    ) -> Dict[str, Any]:
        out = dict(msg)
        reasoning_text = out.pop(_REASONING_TEXT_FIELD, None)

        if out.get("role") != "assistant":
            return out
        if not isinstance(reasoning_text, str) or not reasoning_text:
            return out
        if not interleaved_field:
            return out

        existing = out.get(interleaved_field)
        existing_text = str(existing) if isinstance(existing, str) else ""
        if not existing_text:
            out[interleaved_field] = reasoning_text
        return out

    @classmethod
    def message(
        cls,
        messages: Iterable[Dict[str, Any]],
        *,
        model: Any,
        provider_id: str,
        model_id: str,
        api_type: str,
        provider_options: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Normalize message payloads before provider-specific conversion."""
        del provider_options

        out: List[Dict[str, Any]] = []
        source = [copy.deepcopy(msg) for msg in messages if isinstance(msg, dict)]
        interleaved_field = cls.interleaved_field(model)

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
                            call_copy["id"] = cls.normalize_tool_call_id(
                                str(call_id),
                                provider_id=provider_id,
                                model_id=model_id,
                            )
                        cleaned.append(call_copy)
                    msg["tool_calls"] = cleaned

            if role == "tool":
                tool_call_id = msg.get("tool_call_id")
                if tool_call_id:
                    msg["tool_call_id"] = cls.normalize_tool_call_id(
                        str(tool_call_id),
                        provider_id=provider_id,
                        model_id=model_id,
                    )

            if api_type == "anthropic" or provider_id.lower() == "anthropic" or "claude" in model_id.lower():
                if role in {"assistant", "user"} and isinstance(content, str) and not content:
                    continue

            msg = cls._apply_reasoning_text(msg, interleaved_field=interleaved_field)
            msg = cls._apply_interleaved_reasoning(msg, interleaved_field=interleaved_field)
            if (
                interleaved_field
                and msg.get("role") == "assistant"
                and isinstance(msg.get("tool_calls"), list)
                and msg.get("tool_calls")
                and interleaved_field not in msg
            ):
                # Keep interleaved reasoning key stable for tool-call turns
                # even when no reasoning text is emitted.
                msg[interleaved_field] = ""
            out.append(msg)

            # Some OpenAI-compatible Mistral gateways reject tool->user adjacency.
            if role == "tool" and idx + 1 < len(source):
                next_role = source[idx + 1].get("role")
                if next_role == "user" and ("mistral" in provider_id.lower() or "mistral" in model_id.lower()):
                    out.append({"role": "assistant", "content": _EMPTY_ASSISTANT_PLACEHOLDER})

        out = cls.remap_provider_options(out, provider_id=provider_id, api_type=api_type)
        out = cls.apply_cache_controls(out, provider_id=provider_id, api_type=api_type)
        return out

    @staticmethod
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

    @classmethod
    def anthropic_messages(cls, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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
                                "input": cls._parse_json(fn.get("arguments")),
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

    @classmethod
    def options(
        cls,
        *,
        model: Any,
        session_id: str,
        provider_options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Return provider/model default request options."""
        del session_id
        base: Dict[str, Any] = {}

        provider_id = str(getattr(model, "provider_id", "") or "").lower()
        api_type = str(getattr(model, "api_type", "openai") or "openai").lower()

        if provider_id == "openai" and api_type == "openai":
            # Follow OpenCode behavior: avoid server-side storage unless explicitly requested.
            base["store"] = False

        if provider_options and provider_options.get("litellmProxy") is True:
            base["litellm_proxy"] = True

        return base

    @classmethod
    def provider_options(cls, *, model: Any, options: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Return provider-options payload expected by SDK-level adapters."""
        if not options:
            return {}
        provider_id = str(getattr(model, "provider_id", "") or "")
        api_type = str(getattr(model, "api_type", "openai") or "openai")
        key = cls.sdk_key(provider_id=provider_id, api_type=api_type)
        return {key: dict(options)}

    @staticmethod
    def temperature(model: Any) -> Optional[float]:
        del model
        return ProviderTransform.DEFAULT_TEMPERATURE

    @staticmethod
    def top_p(model: Any) -> Optional[float]:
        del model
        return ProviderTransform.DEFAULT_TOP_P

    @staticmethod
    def top_k(model: Any) -> Optional[int]:
        del model
        return ProviderTransform.DEFAULT_TOP_K

    @classmethod
    def max_output_tokens(cls, model: Any) -> int:
        limit = getattr(model, "limit", None)
        output = getattr(limit, "output", None)
        if isinstance(output, int) and output > 0:
            return min(output, cls.OUTPUT_TOKEN_MAX)
        return cls.OUTPUT_TOKEN_MAX

    @staticmethod
    def variants(model: Any) -> Dict[str, Dict[str, Any]]:
        data = getattr(model, "variants", None)
        if isinstance(data, dict):
            return {
                str(k): dict(v)
                for k, v in data.items()
                if isinstance(k, str) and isinstance(v, dict)
            }
        return {}

    @classmethod
    def resolve_variant(cls, *, model: Any, variant: Optional[str]) -> Dict[str, Any]:
        if not variant:
            return {}
        variants = cls.variants(model)
        resolved = variants.get(str(variant))
        return dict(resolved) if isinstance(resolved, dict) else {}

    @staticmethod
    def schema(model: Any, schema: Dict[str, Any]) -> Dict[str, Any]:
        """Provider-specific schema normalization hook.

        For now this is intentionally conservative and keeps user schema intact.
        """
        del model
        return dict(schema or {})
