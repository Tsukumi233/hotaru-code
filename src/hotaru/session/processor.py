"""Session processor for handling LLM responses and tool execution."""

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..core.id import Identifier
from ..provider import Provider
from ..tool import ToolContext, ToolResult
from ..tool.registry import ToolRegistry
from ..util.log import Log
from .llm import LLM, StreamInput, StreamChunk
from .message import Message, MessageInfo

log = Log.create({"service": "session.processor"})

# Maximum consecutive identical tool calls before triggering doom loop detection
DOOM_LOOP_THRESHOLD = 3


@dataclass
class ToolCallState:
    """State of a tool call in progress."""
    id: str
    name: str
    input_json: str = ""
    input: Dict[str, Any] = field(default_factory=dict)
    status: str = "pending"  # pending, running, completed, error
    output: Optional[str] = None
    error: Optional[str] = None
    start_time: Optional[int] = None
    end_time: Optional[int] = None


@dataclass
class ProcessorResult:
    """Result of processing a message."""
    status: str  # "continue", "stop", "error"
    text: str = ""
    tool_calls: List[ToolCallState] = field(default_factory=list)
    error: Optional[str] = None
    usage: Dict[str, int] = field(default_factory=dict)


class SessionProcessor:
    """Processor for handling LLM responses and tool execution.

    Manages the agentic loop:
    1. Send message to LLM
    2. Process streaming response
    3. Execute tool calls
    4. Continue until done or error
    """

    def __init__(
        self,
        session_id: str,
        model_id: str,
        provider_id: str,
        agent: str,
        cwd: str,
        max_turns: int = 100,
    ):
        """Initialize the processor.

        Args:
            session_id: Session ID
            model_id: Model ID
            provider_id: Provider ID
            agent: Agent name
            cwd: Current working directory
            max_turns: Maximum number of turns
        """
        self.session_id = session_id
        self.model_id = model_id
        self.provider_id = provider_id
        self.agent = agent
        self.cwd = cwd
        self.max_turns = max_turns
        self.turn = 0
        self.messages: List[Dict[str, Any]] = []
        self.tool_calls: Dict[str, ToolCallState] = {}

    async def process(
        self,
        user_message: str,
        system_prompt: Optional[str] = None,
        on_text: Optional[callable] = None,
        on_tool_start: Optional[callable] = None,
        on_tool_end: Optional[callable] = None,
    ) -> ProcessorResult:
        """Process a user message through the agentic loop.

        Args:
            user_message: User's message
            system_prompt: Optional system prompt
            on_text: Callback for text chunks
            on_tool_start: Callback when tool starts
            on_tool_end: Callback when tool ends

        Returns:
            ProcessorResult with final state
        """
        # Add user message to history
        self.messages.append({"role": "user", "content": user_message})

        result = ProcessorResult(status="continue")

        while result.status == "continue" and self.turn < self.max_turns:
            self.turn += 1
            log.info("processing turn", {"turn": self.turn, "session_id": self.session_id})

            # Get tool definitions
            tool_definitions = ToolRegistry.get_tool_definitions()

            # Create stream input
            stream_input = StreamInput(
                session_id=self.session_id,
                model_id=self.model_id,
                provider_id=self.provider_id,
                messages=self.messages.copy(),
                system=system_prompt,
                tools=tool_definitions if tool_definitions else None,
                max_tokens=4096,
            )

            # Process the stream
            turn_result = await self._process_turn(
                stream_input,
                on_text=on_text,
                on_tool_start=on_tool_start,
                on_tool_end=on_tool_end,
            )

            result.text += turn_result.text
            result.tool_calls.extend(turn_result.tool_calls)
            if turn_result.usage:
                for key, value in turn_result.usage.items():
                    result.usage[key] = result.usage.get(key, 0) + value

            if turn_result.error:
                result.status = "error"
                result.error = turn_result.error
                break

            # Check if we should continue
            if not turn_result.tool_calls:
                # No tool calls, we're done
                result.status = "stop"
                break

            # Add assistant message with tool calls to history (OpenAI format)
            assistant_message: Dict[str, Any] = {"role": "assistant"}
            if turn_result.text:
                assistant_message["content"] = turn_result.text
            else:
                assistant_message["content"] = None

            # Add tool calls in OpenAI format
            tool_calls_list = []
            for tc in turn_result.tool_calls:
                tool_calls_list.append({
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.input),
                    },
                })
            assistant_message["tool_calls"] = tool_calls_list

            self.messages.append(assistant_message)

            # Add tool results as separate messages (OpenAI format)
            for tc in turn_result.tool_calls:
                tool_result_message = {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tc.output if tc.status == "completed" else tc.error or "Tool execution failed",
                }
                self.messages.append(tool_result_message)

        if self.turn >= self.max_turns:
            result.status = "error"
            result.error = f"Maximum turns ({self.max_turns}) exceeded"

        return result

    async def _process_turn(
        self,
        stream_input: StreamInput,
        on_text: Optional[callable] = None,
        on_tool_start: Optional[callable] = None,
        on_tool_end: Optional[callable] = None,
    ) -> ProcessorResult:
        """Process a single turn of the conversation.

        Args:
            stream_input: Input for the LLM stream
            on_text: Callback for text chunks
            on_tool_start: Callback when tool starts
            on_tool_end: Callback when tool ends

        Returns:
            ProcessorResult for this turn
        """
        result = ProcessorResult(status="continue")
        current_tool_calls: Dict[str, ToolCallState] = {}

        try:
            async for chunk in LLM.stream(stream_input):
                if chunk.type == "text" and chunk.text:
                    result.text += chunk.text
                    if on_text:
                        await self._call_callback(on_text, chunk.text)

                elif chunk.type == "tool_call_start":
                    tc = ToolCallState(
                        id=chunk.tool_call_id or "",
                        name=chunk.tool_call_name or "",
                        status="pending",
                        start_time=int(time.time() * 1000),
                    )
                    current_tool_calls[tc.id] = tc
                    if on_tool_start:
                        await self._call_callback(on_tool_start, tc.name, tc.id)

                elif chunk.type == "tool_call_delta":
                    if chunk.tool_call_id and chunk.tool_call_id in current_tool_calls:
                        current_tool_calls[chunk.tool_call_id].input_json += chunk.tool_call_input_delta or ""

                elif chunk.type == "tool_call_end" and chunk.tool_call:
                    tc_id = chunk.tool_call.id
                    if tc_id in current_tool_calls:
                        tc = current_tool_calls[tc_id]
                        tc.input = chunk.tool_call.input
                        tc.status = "running"

                        # Execute the tool
                        tool_result = await self._execute_tool(tc.name, tc.input)
                        tc.end_time = int(time.time() * 1000)

                        if tool_result.get("error"):
                            tc.status = "error"
                            tc.error = tool_result["error"]
                        else:
                            tc.status = "completed"
                            tc.output = tool_result.get("output", "")

                        result.tool_calls.append(tc)
                        if on_tool_end:
                            await self._call_callback(on_tool_end, tc.name, tc.id, tc.output, tc.error)

                elif chunk.type == "message_delta" and chunk.usage:
                    result.usage.update(chunk.usage)

                elif chunk.type == "error" and chunk.error:
                    result.status = "error"
                    result.error = chunk.error
                    break

        except Exception as e:
            log.error("turn processing error", {"error": str(e)})
            result.status = "error"
            result.error = str(e)

        return result

    async def _execute_tool(self, tool_name: str, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool.

        Args:
            tool_name: Name of the tool
            tool_input: Tool input parameters

        Returns:
            Dict with output or error
        """
        tool = ToolRegistry.get(tool_name)
        if not tool:
            return {"error": f"Unknown tool: {tool_name}"}

        try:
            # Create tool context
            ctx = ToolContext(
                session_id=self.session_id,
                message_id=Identifier.ascending("message"),
                agent=self.agent,
                call_id=Identifier.ascending("call"),
                extra={"cwd": self.cwd},
            )

            # Validate and parse input
            try:
                args = tool.parameters_type.model_validate(tool_input)
            except Exception as e:
                return {"error": f"Invalid tool input: {e}"}

            # Execute the tool
            result = await tool.execute(args, ctx)

            return {
                "output": result.output,
                "title": result.title,
                "metadata": result.metadata,
            }

        except Exception as e:
            log.error("tool execution error", {"tool": tool_name, "error": str(e)})
            return {"error": str(e)}

    async def _call_callback(self, callback: callable, *args) -> None:
        """Call a callback, handling both sync and async."""
        if asyncio.iscoroutinefunction(callback):
            await callback(*args)
        else:
            callback(*args)
