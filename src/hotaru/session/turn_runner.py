"""Streaming turn runner for session processor."""

from __future__ import annotations

import traceback
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol, runtime_checkable

from ..util.log import Log
from .llm import LLM, StreamInput
from .processor_types import ProcessorResult, ToolCallState

log = Log.create({"service": "session.turn_runner"})


@runtime_checkable
class TurnHost(Protocol):
    """Protocol that the owner of a TurnRunner must implement."""

    async def call_callback(self, callback: Callable[..., Any], *args: Any) -> None: ...

    async def emit_tool_update(self, callback: Optional[Callable[..., Any]], tc: ToolCallState) -> None: ...

    async def execute_tool(
        self,
        *,
        tool_name: str,
        tool_input: Dict[str, Any],
        tc: Optional[ToolCallState] = None,
        on_tool_update: Optional[Callable[..., Any]] = None,
        assistant_message_id: Optional[str] = None,
    ) -> Dict[str, Any]: ...

    def apply_mode_switch_metadata(self, metadata: Dict[str, Any]) -> None: ...

    def recoverable_error(self, error: Exception) -> bool: ...

    def continue_loop_on_deny(self) -> bool: ...


class TurnRunner:
    """Consume model stream and coordinate per-chunk callbacks."""

    def __init__(self, *, host: TurnHost) -> None:
        self.host = host

    @staticmethod
    def _sanitize_text(value: Any) -> str:
        text = str(value or "")
        if not text:
            return ""
        clean: List[str] = []
        changed = False
        for char in text:
            code = ord(char)
            is_surrogate = 0xD800 <= code <= 0xDFFF
            is_c0_control = code < 0x20 and char not in {"\n", "\t"}
            is_c1_control = 0x7F <= code <= 0x9F
            if is_surrogate or is_c0_control or is_c1_control:
                clean.append("\uFFFD")
                changed = True
                continue
            clean.append(char)
        if not changed:
            return text
        return "".join(clean)

    async def run(
        self,
        *,
        stream_input: StreamInput,
        on_text: Optional[callable] = None,
        on_tool_start: Optional[callable] = None,
        on_tool_end: Optional[callable] = None,
        on_tool_update: Optional[callable] = None,
        on_reasoning_start: Optional[callable] = None,
        on_reasoning_delta: Optional[callable] = None,
        on_reasoning_end: Optional[callable] = None,
        assistant_message_id: Optional[str] = None,
    ) -> ProcessorResult:
        result = ProcessorResult(status="continue")
        current_tool_calls: Dict[str, ToolCallState] = {}
        blocked = False
        reasoning_fragments: List[str] = []

        try:
            async for chunk in LLM.stream(stream_input):
                if chunk.type == "text" and chunk.text:
                    text = self._sanitize_text(chunk.text)
                    if not text:
                        continue
                    result.text += text
                    if on_text:
                        await self.host.call_callback(on_text, text)

                elif chunk.type == "tool_call_start":
                    tc = ToolCallState(
                        id=chunk.tool_call_id or "",
                        name=chunk.tool_call_name or "",
                        status="pending",
                        start_time=int(time.time() * 1000),
                    )
                    current_tool_calls[tc.id] = tc
                    if on_tool_start:
                        await self.host.call_callback(on_tool_start, tc.name, tc.id, {})
                    await self.host.emit_tool_update(on_tool_update, tc)

                elif chunk.type == "tool_call_delta":
                    if chunk.tool_call_id and chunk.tool_call_id in current_tool_calls:
                        current_tool_calls[chunk.tool_call_id].input_json += self._sanitize_text(
                            chunk.tool_call_input_delta or ""
                        )

                elif chunk.type == "tool_call_end" and chunk.tool_call:
                    tc_id = chunk.tool_call.id
                    if tc_id in current_tool_calls:
                        tc = current_tool_calls[tc_id]
                        tc.input = chunk.tool_call.input
                        tc.status = "running"

                        if on_tool_start:
                            await self.host.call_callback(on_tool_start, tc.name, tc.id, tc.input)
                        await self.host.emit_tool_update(on_tool_update, tc)

                        tool_result = await self.host.execute_tool(
                            tool_name=tc.name,
                            tool_input=tc.input,
                            tc=tc,
                            on_tool_update=on_tool_update,
                            assistant_message_id=assistant_message_id,
                        )
                        tc.end_time = int(time.time() * 1000)

                        if tool_result.get("error"):
                            tc.status = "error"
                            tc.error = tool_result["error"]
                            if tool_result.get("blocked") and not self.host.continue_loop_on_deny():
                                blocked = True
                        else:
                            tc.status = "completed"
                            tc.output = tool_result.get("output", "")
                            tc.title = str(tool_result.get("title") or "") or None
                            tc.attachments = tool_result.get("attachments", [])
                            tc.metadata = dict(tool_result.get("metadata", {}) or {})
                            self.host.apply_mode_switch_metadata(tc.metadata)

                        await self.host.emit_tool_update(on_tool_update, tc)

                        result.tool_calls.append(tc)
                        if on_tool_end:
                            callback_metadata = dict(tool_result.get("metadata", {}))
                            if tc.attachments:
                                callback_metadata["attachments"] = tc.attachments
                            await self.host.call_callback(
                                on_tool_end,
                                tc.name,
                                tc.id,
                                tc.output,
                                tc.error,
                                tool_result.get("title", ""),
                                callback_metadata,
                            )
                        if blocked:
                            result.status = "stop"
                            break

                elif chunk.type == "reasoning_start":
                    if on_reasoning_start:
                        await self.host.call_callback(
                            on_reasoning_start,
                            chunk.reasoning_id,
                            dict(chunk.provider_metadata or {}),
                        )

                elif chunk.type == "reasoning_delta":
                    piece = self._sanitize_text(chunk.reasoning_text or "")
                    if piece:
                        reasoning_fragments.append(piece)
                    if on_reasoning_delta:
                        await self.host.call_callback(
                            on_reasoning_delta,
                            chunk.reasoning_id,
                            piece,
                            dict(chunk.provider_metadata or {}),
                        )

                elif chunk.type == "reasoning_end":
                    if on_reasoning_end:
                        await self.host.call_callback(
                            on_reasoning_end,
                            chunk.reasoning_id,
                            dict(chunk.provider_metadata or {}),
                        )

                elif chunk.type == "message_delta" and chunk.usage:
                    result.usage.update(chunk.usage)
                    if chunk.stop_reason:
                        result.stop_reason = chunk.stop_reason
                elif chunk.type == "message_delta" and chunk.stop_reason:
                    result.stop_reason = chunk.stop_reason

                elif chunk.type == "error" and chunk.error:
                    result.status = "error"
                    result.error = chunk.error
                    break

        except Exception as e:
            if self.host.recoverable_error(e):
                log.warn(
                    "recoverable turn processing error",
                    {
                        "error": str(e),
                        "error_type": type(e).__name__,
                    },
                )
                result.status = "error"
                result.error = str(e)
            else:
                log.error(
                    "unexpected error in turn processing",
                    {
                        "error": str(e),
                        "error_type": type(e).__name__,
                        "traceback": traceback.format_exc(),
                    },
                )
                raise

        result.reasoning_text = "".join(reasoning_fragments)
        return result
