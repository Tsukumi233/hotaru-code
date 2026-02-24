"""Streaming turn runner for session processor."""

from __future__ import annotations

import traceback
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

from ..util.log import Log
from .llm import LLM, StreamInput
from .processor_types import ProcessorResult, ToolCallState

log = Log.create({"service": "session.turn_runner"})


class TurnRunner:
    """Consume model stream and coordinate per-chunk callbacks."""

    def __init__(
        self,
        *,
        call_callback: Callable[..., Awaitable[None]],
        emit_tool_update: Callable[[Optional[callable], ToolCallState], Awaitable[None]],
        execute_tool: Callable[..., Awaitable[Dict[str, Any]]],
        apply_mode_switch_metadata: Callable[[Dict[str, Any]], None],
        recoverable_error: Callable[[Exception], bool],
        continue_loop_on_deny: Callable[[], bool],
    ) -> None:
        self.call_callback = call_callback
        self.emit_tool_update = emit_tool_update
        self.execute_tool = execute_tool
        self.apply_mode_switch_metadata = apply_mode_switch_metadata
        self.recoverable_error = recoverable_error
        self.continue_loop_on_deny = continue_loop_on_deny

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
                        await self.call_callback(on_text, text)

                elif chunk.type == "tool_call_start":
                    tc = ToolCallState(
                        id=chunk.tool_call_id or "",
                        name=chunk.tool_call_name or "",
                        status="pending",
                        start_time=int(time.time() * 1000),
                    )
                    current_tool_calls[tc.id] = tc
                    if on_tool_start:
                        await self.call_callback(on_tool_start, tc.name, tc.id, {})
                    await self.emit_tool_update(on_tool_update, tc)

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
                            await self.call_callback(on_tool_start, tc.name, tc.id, tc.input)
                        await self.emit_tool_update(on_tool_update, tc)

                        tool_result = await self.execute_tool(
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
                            if tool_result.get("blocked") and not self.continue_loop_on_deny():
                                blocked = True
                        else:
                            tc.status = "completed"
                            tc.output = tool_result.get("output", "")
                            tc.title = str(tool_result.get("title") or "") or None
                            tc.attachments = tool_result.get("attachments", [])
                            tc.metadata = dict(tool_result.get("metadata", {}) or {})
                            self.apply_mode_switch_metadata(tc.metadata)

                        await self.emit_tool_update(on_tool_update, tc)

                        result.tool_calls.append(tc)
                        if on_tool_end:
                            callback_metadata = dict(tool_result.get("metadata", {}))
                            if tc.attachments:
                                callback_metadata["attachments"] = tc.attachments
                            await self.call_callback(
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
                        await self.call_callback(
                            on_reasoning_start,
                            chunk.reasoning_id,
                            dict(chunk.provider_metadata or {}),
                        )

                elif chunk.type == "reasoning_delta":
                    piece = self._sanitize_text(chunk.reasoning_text or "")
                    if piece:
                        reasoning_fragments.append(piece)
                    if on_reasoning_delta:
                        await self.call_callback(
                            on_reasoning_delta,
                            chunk.reasoning_id,
                            piece,
                            dict(chunk.provider_metadata or {}),
                        )

                elif chunk.type == "reasoning_end":
                    if on_reasoning_end:
                        await self.call_callback(
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
            if self.recoverable_error(e):
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
