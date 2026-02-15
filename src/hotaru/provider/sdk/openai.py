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

        stream = await self.client.chat.completions.create(**params)

        yield StreamChunk(type="message_start")

        async for chunk in stream:
            if not chunk.choices:
                # Final chunk with usage
                if chunk.usage:
                    yield StreamChunk(
                        type="message_delta",
                        usage={
                            "input_tokens": chunk.usage.prompt_tokens,
                            "output_tokens": chunk.usage.completion_tokens,
                        },
                    )
                continue

            choice = chunk.choices[0]
            delta = choice.delta

            # Handle text content
            if delta.content:
                yield StreamChunk(type="text", text=delta.content)

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
                        current["arguments"] += tc.function.arguments
                        yield StreamChunk(
                            type="tool_call_delta",
                            tool_call_id=current["id"] or f"tool_call_{idx}",
                            tool_call_input_delta=tc.function.arguments,
                        )

            # Handle finish reason
            if choice.finish_reason:
                # Emit completed tool calls
                for idx in sorted(tool_calls_in_progress.keys()):
                    tc_data = tool_calls_in_progress[idx]
                    try:
                        args = json.loads(tc_data["arguments"]) if tc_data["arguments"] else {}
                    except json.JSONDecodeError:
                        args = {}

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
