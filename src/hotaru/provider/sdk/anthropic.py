"""Anthropic SDK wrapper for streaming chat completions."""

import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

from anthropic import AsyncAnthropic
from anthropic.types import (
    ContentBlock,
    ContentBlockDeltaEvent,
    ContentBlockStartEvent,
    ContentBlockStopEvent,
    Message,
    MessageDeltaEvent,
    MessageStartEvent,
    MessageStopEvent,
    RawMessageStreamEvent,
    TextBlock,
    TextDelta,
    ToolResultBlockParam,
    ToolUseBlock,
)

from ..transform import ProviderTransform
from ...util.log import Log

log = Log.create({"service": "sdk.anthropic"})


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


class AnthropicSDK:
    """Wrapper for Anthropic API with streaming support."""

    def __init__(self, api_key: str, base_url: Optional[str] = None):
        """Initialize the Anthropic SDK.

        Args:
            api_key: Anthropic API key
            base_url: Optional custom base URL
        """
        self.client = AsyncAnthropic(
            api_key=api_key,
            base_url=base_url,
        )

    async def stream(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        system: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Any] = None,
        max_tokens: int = ProviderTransform.OUTPUT_TOKEN_MAX,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        stop_sequences: Optional[List[str]] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream a chat completion.

        Args:
            model: Model ID (e.g., "claude-sonnet-4-20250514")
            messages: List of messages in Anthropic format
            system: System prompt
            tools: List of tool definitions
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            top_p: Top-p sampling
            stop_sequences: Stop sequences

        Yields:
            StreamChunk objects for each event
        """
        params: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
        }

        if system:
            params["system"] = system
        if tools:
            params["tools"] = tools
        if tool_choice is not None:
            params["tool_choice"] = tool_choice
        if temperature is not None:
            params["temperature"] = temperature
        if top_p is not None:
            params["top_p"] = top_p
        if stop_sequences:
            params["stop_sequences"] = stop_sequences
        if options:
            reserved = {
                "model",
                "messages",
                "max_tokens",
                "system",
                "tools",
                "tool_choice",
                "temperature",
                "top_p",
                "stop_sequences",
            }
            for key, value in options.items():
                if key in reserved:
                    continue
                params[key] = value

        log.info("streaming", {"model": model, "message_count": len(messages)})

        block_kind_by_index: Dict[int, str] = {}
        tool_state_by_index: Dict[int, Dict[str, Any]] = {}
        reasoning_id_by_index: Dict[int, str] = {}

        async with self.client.messages.stream(**params) as stream:
            async for event in stream:
                if isinstance(event, MessageStartEvent):
                    usage: Dict[str, int] = {"input_tokens": event.message.usage.input_tokens}
                    if getattr(event.message.usage, "cache_read_input_tokens", None):
                        usage["cache_read_tokens"] = int(event.message.usage.cache_read_input_tokens)
                    if getattr(event.message.usage, "cache_creation_input_tokens", None):
                        usage["cache_write_tokens"] = int(event.message.usage.cache_creation_input_tokens)
                    yield StreamChunk(
                        type="message_start",
                        usage=usage,
                    )

                elif isinstance(event, ContentBlockStartEvent):
                    index = int(getattr(event, "index", 0) or 0)
                    if isinstance(event.content_block, TextBlock):
                        block_kind_by_index[index] = "text"
                    elif isinstance(event.content_block, ToolUseBlock):
                        block_kind_by_index[index] = "tool"
                        tool_state_by_index[index] = {
                            "id": event.content_block.id,
                            "name": event.content_block.name,
                            "input_json": json.dumps(event.content_block.input or {}),
                        }
                        yield StreamChunk(
                            type="tool_call_start",
                            tool_call_id=event.content_block.id,
                            tool_call_name=event.content_block.name,
                        )
                    else:
                        block_type = str(getattr(event.content_block, "type", "") or "")
                        if block_type in {"thinking", "reasoning"}:
                            reasoning_id = str(
                                getattr(event.content_block, "id", "") or f"reasoning_{index}"
                            )
                            block_kind_by_index[index] = "reasoning"
                            reasoning_id_by_index[index] = reasoning_id
                            metadata = {"index": index, "block_type": block_type}
                            yield StreamChunk(
                                type="reasoning_start",
                                reasoning_id=reasoning_id,
                                provider_metadata=metadata,
                            )
                            initial = getattr(event.content_block, "thinking", None)
                            if isinstance(initial, str) and initial:
                                yield StreamChunk(
                                    type="reasoning_delta",
                                    reasoning_id=reasoning_id,
                                    reasoning_text=initial,
                                    provider_metadata=metadata,
                                )

                elif isinstance(event, ContentBlockDeltaEvent):
                    index = int(getattr(event, "index", 0) or 0)
                    kind = block_kind_by_index.get(index)
                    if kind == "text":
                        text = getattr(event.delta, "text", None)
                        if isinstance(text, str) and text:
                            yield StreamChunk(type="text", text=text)
                    elif kind == "tool":
                        partial = getattr(event.delta, "partial_json", None)
                        state = tool_state_by_index.get(index)
                        if isinstance(partial, str) and partial and state:
                            state["input_json"] = str(state.get("input_json") or "") + partial
                            yield StreamChunk(
                                type="tool_call_delta",
                                tool_call_id=str(state.get("id") or ""),
                                tool_call_input_delta=partial,
                            )
                    elif kind == "reasoning":
                        delta_text = getattr(event.delta, "thinking", None)
                        if not isinstance(delta_text, str) or not delta_text:
                            candidate = getattr(event.delta, "text", None)
                            delta_text = candidate if isinstance(candidate, str) else ""
                        if delta_text:
                            reasoning_id = reasoning_id_by_index.get(index) or f"reasoning_{index}"
                            yield StreamChunk(
                                type="reasoning_delta",
                                reasoning_id=reasoning_id,
                                reasoning_text=delta_text,
                                provider_metadata={
                                    "index": index,
                                    "delta_type": str(getattr(event.delta, "type", "") or ""),
                                },
                            )

                elif isinstance(event, ContentBlockStopEvent):
                    index = int(getattr(event, "index", 0) or 0)
                    kind = block_kind_by_index.pop(index, None)
                    if kind == "tool":
                        state = tool_state_by_index.pop(index, None) or {}
                        raw_input = str(state.get("input_json") or "")
                        try:
                            tool_input = json.loads(raw_input) if raw_input else {}
                        except json.JSONDecodeError:
                            tool_input = {}
                        yield StreamChunk(
                            type="tool_call_end",
                            tool_call=ToolCall(
                                id=str(state.get("id") or ""),
                                name=str(state.get("name") or ""),
                                input=tool_input,
                            ),
                        )
                    elif kind == "reasoning":
                        reasoning_id = reasoning_id_by_index.pop(index, None) or f"reasoning_{index}"
                        yield StreamChunk(
                            type="reasoning_end",
                            reasoning_id=reasoning_id,
                            provider_metadata={"index": index},
                        )

                elif isinstance(event, MessageDeltaEvent):
                    yield StreamChunk(
                        type="message_delta",
                        stop_reason=event.delta.stop_reason,
                        usage={"output_tokens": event.usage.output_tokens},
                    )

                elif isinstance(event, MessageStopEvent):
                    for index, state in list(tool_state_by_index.items()):
                        raw_input = str(state.get("input_json") or "")
                        try:
                            tool_input = json.loads(raw_input) if raw_input else {}
                        except json.JSONDecodeError:
                            tool_input = {}
                        yield StreamChunk(
                            type="tool_call_end",
                            tool_call=ToolCall(
                                id=str(state.get("id") or ""),
                                name=str(state.get("name") or ""),
                                input=tool_input,
                            ),
                        )
                        tool_state_by_index.pop(index, None)
                    for index, reasoning_id in list(reasoning_id_by_index.items()):
                        yield StreamChunk(
                            type="reasoning_end",
                            reasoning_id=reasoning_id,
                            provider_metadata={"index": index},
                        )
                        reasoning_id_by_index.pop(index, None)
                    yield StreamChunk(type="message_end")

    async def complete(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        system: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Any] = None,
        max_tokens: int = ProviderTransform.OUTPUT_TOKEN_MAX,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        stop_sequences: Optional[List[str]] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> StreamResult:
        """Non-streaming chat completion.

        Args:
            model: Model ID
            messages: List of messages
            system: System prompt
            tools: List of tool definitions
            max_tokens: Maximum tokens
            temperature: Sampling temperature
            top_p: Top-p sampling
            stop_sequences: Stop sequences

        Returns:
            StreamResult with full response
        """
        result = StreamResult()

        async for chunk in self.stream(
            model=model,
            messages=messages,
            system=system,
            tools=tools,
            tool_choice=tool_choice,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            stop_sequences=stop_sequences,
            options=options,
        ):
            if chunk.type == "text" and chunk.text:
                result.text += chunk.text
            elif chunk.type == "tool_call_end" and chunk.tool_call:
                result.tool_calls.append(chunk.tool_call)
            elif chunk.type == "message_start" and chunk.usage:
                result.usage.update(chunk.usage)
            elif chunk.type == "message_delta":
                if chunk.usage:
                    result.usage.update(chunk.usage)
                if chunk.stop_reason:
                    result.stop_reason = chunk.stop_reason

        return result

    @staticmethod
    def format_tool_result(tool_call_id: str, result: str, is_error: bool = False) -> ToolResultBlockParam:
        """Format a tool result for the API.

        Args:
            tool_call_id: The tool call ID
            result: The result content
            is_error: Whether this is an error result

        Returns:
            ToolResultBlockParam for the API
        """
        return {
            "type": "tool_result",
            "tool_use_id": tool_call_id,
            "content": result,
            "is_error": is_error,
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
            "name": name,
            "description": description,
            "input_schema": parameters,
        }
