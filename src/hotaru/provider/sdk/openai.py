"""OpenAI SDK wrapper for streaming chat completions."""

import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional

from openai import AsyncOpenAI
from openai.types.chat import (
    ChatCompletionChunk,
    ChatCompletionMessageParam,
    ChatCompletionToolParam,
)

from ...util.log import Log

log = Log.create({"service": "sdk.openai"})


@dataclass
class ToolCall:
    """Represents a tool call from the model."""
    id: str
    name: str
    input: Dict[str, Any]


@dataclass
class StreamChunk:
    """A chunk from the streaming response."""
    type: str  # "text", "tool_call_*", "reasoning_*", "message_*"
    text: Optional[str] = None
    tool_call: Optional[ToolCall] = None
    tool_call_id: Optional[str] = None
    tool_call_name: Optional[str] = None
    tool_call_input_delta: Optional[str] = None
    reasoning_id: Optional[str] = None
    reasoning_text: Optional[str] = None
    provider_metadata: Optional[Dict[str, Any]] = None
    usage: Optional[Dict[str, int]] = None
    stop_reason: Optional[str] = None


@dataclass
class StreamResult:
    """Result of a streaming completion."""
    text: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    usage: Dict[str, int] = field(default_factory=dict)
    stop_reason: Optional[str] = None


class OpenAISDK:
    """Wrapper for OpenAI API with streaming support."""

    def __init__(self, api_key: str, base_url: Optional[str] = None):
        """Initialize the OpenAI SDK.

        Args:
            api_key: OpenAI API key
            base_url: Optional custom base URL
        """
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
        )

    @staticmethod
    def _extract_reasoning_text(delta: Any) -> str:
        for key in ("reasoning", "reasoning_content"):
            value = getattr(delta, key, None)
            if isinstance(value, str) and value:
                return value
        details = getattr(delta, "reasoning_details", None)
        if isinstance(details, str) and details:
            return details
        if isinstance(details, list):
            chunks: List[str] = []
            for item in details:
                if isinstance(item, str):
                    chunks.append(item)
                elif isinstance(item, dict):
                    for field in ("text", "content", "reasoning"):
                        text = item.get(field)
                        if isinstance(text, str) and text:
                            chunks.append(text)
                            break
            return "".join(chunks)
        return ""

    @staticmethod
    def _field(data: Any, key: str) -> Any:
        if isinstance(data, dict):
            return data.get(key)
        return getattr(data, key, None)

    @classmethod
    def _field_any(cls, data: Any, *keys: str) -> Any:
        for key in keys:
            value = cls._field(data, key)
            if value is not None:
                return value
        return None

    @staticmethod
    def _to_int(value: Any) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _sanitize_text(value: Any) -> str:
        text = str(value or "")
        if not text:
            return ""
        clean = []
        changed = False
        for char in text:
            code = ord(char)
            is_surrogate = 0xD800 <= code <= 0xDFFF
            is_unsupported_control = code < 0x20 and char not in {"\n", "\r", "\t"}
            if is_surrogate or is_unsupported_control:
                clean.append("\uFFFD")
                changed = True
                continue
            clean.append(char)
        if changed:
            return "".join(clean)
        return text

    @classmethod
    def _parse_tool_input(cls, raw: str) -> Dict[str, Any]:
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
            return {}
        except json.JSONDecodeError:
            pass

        text = cls._sanitize_text(raw).strip()
        if not text:
            return {}
        try:
            parsed, _ = json.JSONDecoder().raw_decode(text)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
        return {}

    @classmethod
    def _extract_usage(cls, usage: Any) -> Dict[str, int]:
        result: Dict[str, int] = {}

        input_tokens = cls._to_int(cls._field_any(usage, "prompt_tokens", "input_tokens"))
        if input_tokens is not None:
            result["input_tokens"] = input_tokens

        output_tokens = cls._to_int(cls._field_any(usage, "completion_tokens", "output_tokens"))
        if output_tokens is not None:
            result["output_tokens"] = output_tokens

        total_tokens = cls._to_int(cls._field(usage, "total_tokens"))
        if total_tokens is not None:
            result["total_tokens"] = total_tokens

        completion_details = cls._field_any(usage, "completion_tokens_details", "output_tokens_details")
        reasoning_tokens = cls._to_int(cls._field(completion_details, "reasoning_tokens"))
        if reasoning_tokens is None:
            reasoning_tokens = cls._to_int(cls._field(usage, "reasoning_tokens"))
        if reasoning_tokens is not None:
            result["reasoning_tokens"] = reasoning_tokens

        prompt_details = cls._field_any(usage, "prompt_tokens_details", "input_tokens_details")
        cache_read_tokens = cls._to_int(cls._field(prompt_details, "cached_tokens"))
        if cache_read_tokens is None:
            cache_read_tokens = cls._to_int(cls._field(usage, "cache_read_tokens"))
        if cache_read_tokens is not None:
            result["cache_read_tokens"] = cache_read_tokens

        cache_write_tokens = cls._to_int(
            cls._field_any(usage, "cache_creation_input_tokens", "cache_write_tokens")
        )
        if cache_write_tokens is not None:
            result["cache_write_tokens"] = cache_write_tokens

        return result

    async def stream(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Any] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        stop: Optional[List[str]] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream a chat completion.

        Args:
            model: Model ID (e.g., "gpt-4")
            messages: List of messages in OpenAI format
            tools: List of tool definitions
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            top_p: Top-p sampling
            stop: Stop sequences

        Yields:
            StreamChunk objects for each event
        """
        params: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        if tools:
            params["tools"] = tools
        if tool_choice is not None:
            params["tool_choice"] = tool_choice
        if max_tokens is not None:
            params["max_tokens"] = max_tokens
        if temperature is not None:
            params["temperature"] = temperature
        if top_p is not None:
            params["top_p"] = top_p
        if stop:
            params["stop"] = stop
        if options:
            reserved = {
                "model",
                "messages",
                "stream",
                "stream_options",
                "tools",
                "tool_choice",
                "max_tokens",
                "temperature",
                "top_p",
                "stop",
            }
            for key, value in options.items():
                if key in reserved:
                    continue
                params[key] = value

        log.info("streaming", {"model": model, "message_count": len(messages)})

        # Track tool calls being built (OpenAI sends them incrementally)
        tool_calls_in_progress: Dict[int, Dict[str, Any]] = {}
        reasoning_active = False
        reasoning_id = "reasoning_0"

        stream = await self.client.chat.completions.create(**params)

        yield StreamChunk(type="message_start")

        iterator = stream.__aiter__()
        while True:
            try:
                chunk = await anext(iterator)
            except StopAsyncIteration:
                break
            except UnicodeDecodeError as e:
                log.warn("skipping undecodable stream chunk", {"error": str(e)})
                continue
            except json.JSONDecodeError as e:
                log.warn("skipping malformed stream chunk", {"error": str(e)})
                continue
            if not chunk.choices:
                # Final chunk with usage
                if chunk.usage:
                    usage_payload = self._extract_usage(chunk.usage)
                    if not usage_payload:
                        continue
                    yield StreamChunk(
                        type="message_delta",
                        usage=usage_payload,
                    )
                continue

            choice = chunk.choices[0]
            delta = choice.delta

            # Handle text content
            if delta.content:
                text = self._sanitize_text(delta.content)
                if text:
                    yield StreamChunk(type="text", text=text)

            reasoning_delta = self._sanitize_text(self._extract_reasoning_text(delta))
            if reasoning_delta:
                if not reasoning_active:
                    reasoning_active = True
                    yield StreamChunk(
                        type="reasoning_start",
                        reasoning_id=reasoning_id,
                    )
                yield StreamChunk(
                    type="reasoning_delta",
                    reasoning_id=reasoning_id,
                    reasoning_text=reasoning_delta,
                )

            # Handle tool calls
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index

                    if idx not in tool_calls_in_progress:
                        # New tool call
                        tool_calls_in_progress[idx] = {
                            "id": tc.id or "",
                            "name": tc.function.name if tc.function else "",
                            "arguments": "",
                            "started": False,
                        }

                    current = tool_calls_in_progress[idx]
                    if tc.id:
                        current["id"] = tc.id
                    if tc.function and tc.function.name:
                        current["name"] = tc.function.name

                    if (not current["started"]) and current["id"] and current["name"]:
                        current["started"] = True
                        yield StreamChunk(
                            type="tool_call_start",
                            tool_call_id=current["id"],
                            tool_call_name=current["name"],
                        )

                    # Accumulate arguments
                    if tc.function and tc.function.arguments:
                        arguments_delta = self._sanitize_text(tc.function.arguments)
                        if not arguments_delta:
                            continue
                        current["arguments"] += arguments_delta
                        yield StreamChunk(
                            type="tool_call_delta",
                            tool_call_id=current["id"] or f"tool_call_{idx}",
                            tool_call_input_delta=arguments_delta,
                        )

            # Handle finish reason
            if choice.finish_reason:
                if reasoning_active:
                    yield StreamChunk(
                        type="reasoning_end",
                        reasoning_id=reasoning_id,
                    )
                    reasoning_active = False
                # Emit completed tool calls
                for idx in sorted(tool_calls_in_progress.keys()):
                    tc_data = tool_calls_in_progress[idx]
                    args = self._parse_tool_input(str(tc_data.get("arguments") or ""))

                    yield StreamChunk(
                        type="tool_call_end",
                        tool_call=ToolCall(
                            id=tc_data["id"],
                            name=tc_data["name"],
                            input=args,
                        ),
                    )
                tool_calls_in_progress.clear()

                yield StreamChunk(
                    type="message_delta",
                    stop_reason=choice.finish_reason,
                )

        if reasoning_active:
            yield StreamChunk(
                type="reasoning_end",
                reasoning_id=reasoning_id,
            )

        yield StreamChunk(type="message_end")

    async def complete(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Any] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        stop: Optional[List[str]] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> StreamResult:
        """Non-streaming chat completion.

        Args:
            model: Model ID
            messages: List of messages
            tools: List of tool definitions
            max_tokens: Maximum tokens
            temperature: Sampling temperature
            top_p: Top-p sampling
            stop: Stop sequences

        Returns:
            StreamResult with full response
        """
        result = StreamResult()

        async for chunk in self.stream(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            stop=stop,
            options=options,
        ):
            if chunk.type == "text" and chunk.text:
                result.text += chunk.text
            elif chunk.type == "tool_call_end" and chunk.tool_call:
                result.tool_calls.append(chunk.tool_call)
            elif chunk.type == "message_delta":
                if chunk.usage:
                    result.usage.update(chunk.usage)
                if chunk.stop_reason:
                    result.stop_reason = chunk.stop_reason

        return result

    @staticmethod
    def format_tool_result(tool_call_id: str, result: str) -> Dict[str, Any]:
        """Format a tool result for the API.

        Args:
            tool_call_id: The tool call ID
            result: The result content

        Returns:
            Tool result message dict
        """
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": result,
        }

    @staticmethod
    def format_tool_definition(
        name: str,
        description: str,
        parameters: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Format a tool definition for the API.

        Args:
            name: Tool name
            description: Tool description
            parameters: JSON Schema for parameters

        Returns:
            Tool definition dict
        """
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            },
        }
