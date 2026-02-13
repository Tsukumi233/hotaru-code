"""LLM streaming interface.

Provides a unified interface for streaming chat completions from different providers.
"""

import os
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

from pydantic import BaseModel

from ..agent import Agent
from ..provider import Provider
from ..provider.sdk.anthropic import AnthropicSDK, StreamChunk as AnthropicChunk, ToolCall
from ..provider.sdk.openai import OpenAISDK, StreamChunk as OpenAIChunk
from ..util.log import Log

log = Log.create({"service": "llm"})


@dataclass
class StreamChunk:
    """Unified stream chunk across providers."""
    type: str  # "text", "tool_call_start", "tool_call_delta", "tool_call_end", "message_start", "message_end", "error"
    text: Optional[str] = None
    tool_call: Optional[ToolCall] = None
    tool_call_id: Optional[str] = None
    tool_call_name: Optional[str] = None
    tool_call_input_delta: Optional[str] = None
    usage: Optional[Dict[str, int]] = None
    stop_reason: Optional[str] = None
    error: Optional[str] = None


@dataclass
class StreamInput:
    """Input for streaming completion."""
    session_id: str
    model_id: str
    provider_id: str
    messages: List[Dict[str, Any]]
    system: Optional[str] = None
    tools: Optional[List[Dict[str, Any]]] = None
    max_tokens: int = 4096
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    options: Optional[Dict[str, Any]] = None


@dataclass
class StreamResult:
    """Result of a streaming completion."""
    text: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    usage: Dict[str, int] = field(default_factory=dict)
    stop_reason: Optional[str] = None


class LLM:
    """LLM streaming interface.

    Provides a unified interface for streaming chat completions.
    """

    @classmethod
    async def stream(cls, input: StreamInput) -> AsyncIterator[StreamChunk]:
        """Stream a chat completion.

        Args:
            input: StreamInput with model, messages, etc.

        Yields:
            StreamChunk objects for each event
        """
        provider = await Provider.get(input.provider_id)
        if not provider:
            yield StreamChunk(type="error", error=f"Provider '{input.provider_id}' not found")
            return

        api_key = provider.key
        if not api_key:
            # Try to get from environment
            for env_var in provider.env:
                api_key = os.environ.get(env_var)
                if api_key:
                    break

        if not api_key:
            yield StreamChunk(type="error", error=f"No API key found for provider '{input.provider_id}'")
            return

        model = provider.models.get(input.model_id)
        if not model:
            yield StreamChunk(type="error", error=f"Model '{input.model_id}' not found")
            return

        log.info("streaming", {
            "provider_id": input.provider_id,
            "model_id": input.model_id,
            "session_id": input.session_id,
        })

        # Get base URL from model or provider options
        base_url = model.api_url or provider.options.get("baseURL")

        # Determine API type from model or provider options
        api_type = getattr(model, 'api_type', None) or provider.options.get("type", "openai")

        try:
            if api_type == "anthropic":
                # Use Anthropic SDK
                async for chunk in cls._stream_anthropic(
                    api_key=api_key,
                    model=model.api_id,
                    messages=input.messages,
                    base_url=base_url,
                    system=input.system,
                    tools=input.tools,
                    max_tokens=input.max_tokens,
                    temperature=input.temperature,
                    top_p=input.top_p,
                    options=input.options,
                ):
                    yield chunk
            else:
                # Default to OpenAI-compatible (works for most providers)
                async for chunk in cls._stream_openai(
                    api_key=api_key,
                    base_url=base_url,
                    model=model.api_id,
                    messages=input.messages,
                    system=input.system,
                    tools=input.tools,
                    max_tokens=input.max_tokens,
                    temperature=input.temperature,
                    top_p=input.top_p,
                    options=input.options,
                ):
                    yield chunk
        except Exception as e:
            log.error("stream error", {"error": str(e)})
            yield StreamChunk(type="error", error=str(e))

    @classmethod
    async def _stream_anthropic(
        cls,
        api_key: str,
        model: str,
        messages: List[Dict[str, Any]],
        base_url: Optional[str] = None,
        system: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: int = 4096,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream from Anthropic API."""
        sdk = AnthropicSDK(api_key=api_key, base_url=base_url)

        async for chunk in sdk.stream(
            model=model,
            messages=messages,
            system=system,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            options=options,
        ):
            yield StreamChunk(
                type=chunk.type,
                text=chunk.text,
                tool_call=chunk.tool_call,
                tool_call_id=chunk.tool_call_id,
                tool_call_name=chunk.tool_call_name,
                tool_call_input_delta=chunk.tool_call_input_delta,
                usage=chunk.usage,
                stop_reason=chunk.stop_reason,
            )

    @classmethod
    async def _stream_openai(
        cls,
        api_key: str,
        model: str,
        messages: List[Dict[str, Any]],
        base_url: Optional[str] = None,
        system: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: int = 4096,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream from OpenAI-compatible API."""
        sdk = OpenAISDK(api_key=api_key, base_url=base_url)

        # Prepend system message if provided
        if system:
            messages = [{"role": "system", "content": system}] + messages

        async for chunk in sdk.stream(
            model=model,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            options=options,
        ):
            yield StreamChunk(
                type=chunk.type,
                text=chunk.text,
                tool_call=chunk.tool_call,
                tool_call_id=chunk.tool_call_id,
                tool_call_name=chunk.tool_call_name,
                tool_call_input_delta=chunk.tool_call_input_delta,
                usage=chunk.usage,
                stop_reason=chunk.stop_reason,
            )

    @classmethod
    async def complete(cls, input: StreamInput) -> StreamResult:
        """Non-streaming completion.

        Args:
            input: StreamInput with model, messages, etc.

        Returns:
            StreamResult with full response
        """
        result = StreamResult()

        async for chunk in cls.stream(input):
            if chunk.type == "text" and chunk.text:
                result.text += chunk.text
            elif chunk.type == "tool_call_end" and chunk.tool_call:
                result.tool_calls.append(chunk.tool_call)
            elif chunk.type == "message_delta":
                if chunk.usage:
                    result.usage.update(chunk.usage)
                if chunk.stop_reason:
                    result.stop_reason = chunk.stop_reason
            elif chunk.type == "error" and chunk.error:
                raise RuntimeError(chunk.error)

        return result
