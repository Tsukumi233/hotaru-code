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
    type: str  # "text", "tool_call_start", "tool_call_delta", "tool_call_end", "message_start", "message_end"
    text: Optional[str] = None
    tool_call: Optional[ToolCall] = None
    tool_call_id: Optional[str] = None
    tool_call_name: Optional[str] = None
    tool_call_input_delta: Optional[str] = None
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
        max_tokens: int = 4096,
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
                "temperature",
                "top_p",
                "stop_sequences",
            }
            for key, value in options.items():
                if key in reserved:
                    continue
                params[key] = value

        log.info("streaming", {"model": model, "message_count": len(messages)})

        # Track current tool call being built
        current_tool_id: Optional[str] = None
        current_tool_name: Optional[str] = None
        current_tool_input: str = ""

        async with self.client.messages.stream(**params) as stream:
            async for event in stream:
                if isinstance(event, MessageStartEvent):
                    yield StreamChunk(
                        type="message_start",
                        usage={"input_tokens": event.message.usage.input_tokens},
                    )

                elif isinstance(event, ContentBlockStartEvent):
                    if isinstance(event.content_block, TextBlock):
                        pass  # Text will come in deltas
                    elif isinstance(event.content_block, ToolUseBlock):
                        current_tool_id = event.content_block.id
                        current_tool_name = event.content_block.name
                        current_tool_input = ""
                        yield StreamChunk(
                            type="tool_call_start",
                            tool_call_id=current_tool_id,
                            tool_call_name=current_tool_name,
                        )

                elif isinstance(event, ContentBlockDeltaEvent):
                    if hasattr(event.delta, "text"):
                        yield StreamChunk(type="text", text=event.delta.text)
                    elif hasattr(event.delta, "partial_json"):
                        current_tool_input += event.delta.partial_json
                        yield StreamChunk(
                            type="tool_call_delta",
                            tool_call_id=current_tool_id,
                            tool_call_input_delta=event.delta.partial_json,
                        )

                elif isinstance(event, ContentBlockStopEvent):
                    if current_tool_id and current_tool_name:
                        try:
                            tool_input = json.loads(current_tool_input) if current_tool_input else {}
                        except json.JSONDecodeError:
                            tool_input = {}

                        yield StreamChunk(
                            type="tool_call_end",
                            tool_call=ToolCall(
                                id=current_tool_id,
                                name=current_tool_name,
                                input=tool_input,
                            ),
                        )
                        current_tool_id = None
                        current_tool_name = None
                        current_tool_input = ""

                elif isinstance(event, MessageDeltaEvent):
                    yield StreamChunk(
                        type="message_delta",
                        stop_reason=event.delta.stop_reason,
                        usage={"output_tokens": event.usage.output_tokens},
                    )

                elif isinstance(event, MessageStopEvent):
                    yield StreamChunk(type="message_end")

    async def complete(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        system: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: int = 4096,
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
