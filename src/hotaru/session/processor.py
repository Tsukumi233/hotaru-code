"""Session processor for handling LLM responses and tool execution."""

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.id import Identifier
from ..permission import RejectedError, CorrectedError, DeniedError
from ..tool import ToolContext
from ..tool.registry import ToolRegistry
from ..util.log import Log
from .llm import LLM, StreamInput, StreamChunk
from .message import Message, MessageInfo

log = Log.create({"service": "session.processor"})

# Maximum consecutive identical tool calls before triggering doom loop detection
DOOM_LOOP_THRESHOLD = 3

_MAX_STEPS_PROMPT_PATH = Path(__file__).parent / "prompt" / "max-steps.txt"
_MAX_STEPS_PROMPT = _MAX_STEPS_PROMPT_PATH.read_text(encoding="utf-8").strip()
_BUILD_SWITCH_PROMPT_PATH = Path(__file__).parent / "prompt" / "build-switch.txt"
_BUILD_SWITCH_PROMPT = _BUILD_SWITCH_PROMPT_PATH.read_text(encoding="utf-8").strip()


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
    attachments: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
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
        worktree: Optional[str] = None,
        max_turns: int = 100,
    ):
        """Initialize the processor.

        Args:
            session_id: Session ID
            model_id: Model ID
            provider_id: Provider ID
            agent: Agent name
            cwd: Current working directory
            worktree: Project worktree/sandbox root
            max_turns: Maximum number of turns
        """
        self.session_id = session_id
        self.model_id = model_id
        self.provider_id = provider_id
        self.agent = agent
        self.cwd = cwd
        self.worktree = worktree or cwd
        self.max_turns = max_turns
        self.turn = 0
        self.messages: List[Dict[str, Any]] = []
        self.tool_calls: Dict[str, ToolCallState] = {}
        self._recent_tool_signatures: List[str] = []
        self._pending_synthetic_users: List[Dict[str, str]] = []
        self._last_assistant_agent: Optional[str] = None

    async def load_history(self) -> None:
        """Load prior conversation history from persisted messages.

        Converts stored ``MessageInfo`` objects into the OpenAI-format
        message list that the LLM expects.  Must be called before
        ``process()`` when resuming an existing session.
        """
        from .session import Session
        from .message import TextPart, ToolInvocationPart

        stored = await Session.get_messages(self.session_id)
        for msg in stored:
            if msg.role == "user":
                # Extract text from parts
                text_parts = [p.text for p in msg.parts if isinstance(p, TextPart)]
                self.messages.append({
                    "role": "user",
                    "content": "".join(text_parts),
                })
            elif msg.role == "assistant":
                if msg.metadata.assistant and msg.metadata.assistant.agent:
                    self._last_assistant_agent = msg.metadata.assistant.agent
                elif msg.metadata.agent:
                    self._last_assistant_agent = msg.metadata.agent
                text_parts = [p.text for p in msg.parts if isinstance(p, TextPart)]
                tool_invocations = [
                    p for p in msg.parts
                    if isinstance(p, ToolInvocationPart)
                ]

                assistant_msg: Dict[str, Any] = {"role": "assistant"}
                assistant_msg["content"] = "".join(text_parts) or None

                # Collect tool calls
                tc_list = []
                tc_results = []
                for ti in tool_invocations:
                    inv = ti.tool_invocation
                    if hasattr(inv, "state") and inv.state == "result":
                        # This is a completed tool call — add both call and result
                        tc_list.append({
                            "id": inv.tool_call_id,
                            "type": "function",
                            "function": {
                                "name": inv.tool_name,
                                "arguments": json.dumps(inv.args) if not isinstance(inv.args, str) else inv.args,
                            },
                        })
                        tc_results.append({
                            "role": "tool",
                            "tool_call_id": inv.tool_call_id,
                            "content": inv.result if hasattr(inv, "result") else "",
                        })

                if tc_list:
                    assistant_msg["tool_calls"] = tc_list

                self.messages.append(assistant_msg)

                # Append tool result messages
                for tr in tc_results:
                    self.messages.append(tr)

        log.info("loaded history", {
            "session_id": self.session_id,
            "message_count": len(self.messages),
        })

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
        from ..core.context import ContextNotFoundError
        from ..project import Instance

        current_instance_dir: Optional[str]
        try:
            current_instance_dir = Instance.directory()
        except ContextNotFoundError:
            current_instance_dir = None

        if (
            current_instance_dir is None
            or Path(current_instance_dir).resolve() != Path(self.cwd).resolve()
        ):
            return await Instance.provide(
                directory=self.cwd,
                fn=lambda: self.process(
                    user_message=user_message,
                    system_prompt=system_prompt,
                    on_text=on_text,
                    on_tool_start=on_tool_start,
                    on_tool_end=on_tool_end,
                ),
            )

        # Add user message to history
        self.messages.append({"role": "user", "content": user_message})

        from ..agent import Agent

        await self._sync_agent_from_session()
        agent_info = await Agent.get(self.agent)
        direct_subagent_result = await self._handle_direct_subagent_mention(user_message, agent_info)
        if direct_subagent_result is not None:
            self.messages.append({"role": "assistant", "content": direct_subagent_result})
            return ProcessorResult(status="stop", text=direct_subagent_result)

        result = ProcessorResult(status="continue")

        while result.status == "continue" and self.turn < self.max_turns:
            self.turn += 1
            await self._sync_agent_from_session()
            agent_info = await Agent.get(self.agent)
            assistant_agent_for_turn = self.agent

            log.info(
                "processing turn",
                {
                    "turn": self.turn,
                    "session_id": self.session_id,
                    "agent": self.agent,
                },
            )

            # Get tool definitions
            max_steps = agent_info.steps if agent_info else None
            is_last_step = bool(max_steps is not None and self.turn >= max_steps)

            tool_definitions: List[Dict[str, Any]] = []
            if not is_last_step:
                tool_definitions = await ToolRegistry.get_tool_definitions(
                    caller_agent=self.agent,
                    provider_id=self.provider_id,
                    model_id=self.model_id,
                )

            # Merge MCP tools
            if not is_last_step:
                try:
                    from ..mcp import MCP

                    mcp_tools = await MCP.tools()
                    for tool_id, tool_info in mcp_tools.items():
                        schema = dict(tool_info.get("input_schema") or {})
                        schema.setdefault("type", "object")
                        schema["additionalProperties"] = False
                        tool_definitions.append({
                            "type": "function",
                            "function": {
                                "name": tool_id,
                                "description": tool_info.get("description", ""),
                                "parameters": schema,
                            },
                        })
                except Exception as e:
                    log.warn("failed to load MCP tools", {"error": str(e)})

            # Filter out disabled tools based on agent permission rules
            if not is_last_step:
                try:
                    from ..permission import Permission

                    if agent_info and agent_info.permission:
                        ruleset = Permission.from_config_list(agent_info.permission)
                        tool_names = [d["function"]["name"] for d in tool_definitions]
                        disabled = Permission.disabled_tools(tool_names, ruleset)
                        if disabled:
                            log.info("filtering disabled tools", {"disabled": list(disabled)})
                            tool_definitions = [
                                d for d in tool_definitions
                                if d["function"]["name"] not in disabled
                            ]
                except Exception as e:
                    log.warn("failed to filter disabled tools", {"error": str(e)})

            await self._insert_mode_reminders(
                current_agent=self.agent,
                previous_assistant_agent=self._last_assistant_agent,
            )
            messages_for_turn = self.messages.copy()
            if is_last_step:
                messages_for_turn.append({
                    "role": "assistant",
                    "content": _MAX_STEPS_PROMPT,
                })

            # Create stream input
            stream_input = StreamInput(
                session_id=self.session_id,
                model_id=self.model_id,
                provider_id=self.provider_id,
                messages=messages_for_turn,
                system=system_prompt,
                tools=tool_definitions if tool_definitions else None,
                max_tokens=4096,
                temperature=agent_info.temperature if agent_info else None,
                top_p=agent_info.top_p if agent_info else None,
                options=(agent_info.options or None) if agent_info else None,
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

            self._last_assistant_agent = assistant_agent_for_turn

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

            if self._pending_synthetic_users:
                await self._flush_synthetic_users()

        if self.turn >= self.max_turns:
            result.status = "error"
            result.error = f"Maximum turns ({self.max_turns}) exceeded"

        return result

    def last_assistant_agent(self) -> str:
        """Return the agent name used for the latest assistant turn."""
        return self._last_assistant_agent or self.agent

    async def _sync_agent_from_session(self) -> None:
        from .session import Session

        session = await Session.get(self.session_id)
        if session and session.agent:
            self.agent = session.agent

    async def _insert_mode_reminders(
        self,
        *,
        current_agent: str,
        previous_assistant_agent: Optional[str],
    ) -> None:
        from .session import Session

        if current_agent != "plan" and previous_assistant_agent != "plan":
            return

        session = await Session.get(self.session_id)
        if not session:
            return

        plan_path = Session.plan_path_for(
            session,
            worktree=self.worktree,
            is_git=bool(self.worktree and self.worktree != "/"),
        )

        if current_agent != "plan" and previous_assistant_agent == "plan":
            if Path(plan_path).exists():
                self._append_reminder_to_latest_user(
                    _BUILD_SWITCH_PROMPT
                    + "\n\n"
                    + f"A plan file exists at {plan_path}. You should execute on the plan defined within it"
                )
            return

        if current_agent == "plan" and previous_assistant_agent != "plan":
            exists = Path(plan_path).exists()
            if not exists:
                Path(plan_path).parent.mkdir(parents=True, exist_ok=True)
            self._append_reminder_to_latest_user(self._build_plan_mode_reminder(plan_path=plan_path, exists=exists))

    def _append_reminder_to_latest_user(self, reminder: str) -> None:
        for message in reversed(self.messages):
            if message.get("role") != "user":
                continue

            content = str(message.get("content") or "")
            if reminder in content:
                return
            message["content"] = f"{content.rstrip()}\n\n{reminder}" if content.strip() else reminder
            return

    def _build_plan_mode_reminder(self, *, plan_path: str, exists: bool) -> str:
        plan_info = (
            f"A plan file already exists at {plan_path}. You can read it and make incremental edits using the edit tool."
            if exists
            else f"No plan file exists yet. You should create your plan at {plan_path} using the write tool."
        )
        return f"""<system-reminder>
Plan mode is active. The user indicated that they do not want you to execute yet -- you MUST NOT make any edits (with the exception of the plan file mentioned below), run any non-readonly tools (including changing configs or making commits), or otherwise make any changes to the system. This supersedes any other instructions you have received.

## Plan File Info:
{plan_info}
You should build your plan incrementally by writing to or editing this file. NOTE that this is the only file you are allowed to edit - other than this you are only allowed to take READ-ONLY actions.

## Plan Workflow

### Phase 1: Initial Understanding
Goal: Gain a comprehensive understanding of the user's request by reading through code and asking them questions. Critical: In this phase you should only use the explore subagent type.

1. Focus on understanding the user's request and the code associated with their request.
2. Launch up to 3 explore agents in parallel only when scope is uncertain; otherwise use one.
3. After exploration, use question tool to clarify ambiguities.

### Phase 2: Design
Goal: Design an implementation approach.
Use general agent(s) to draft the implementation strategy based on exploration results.

### Phase 3: Review
Goal: Ensure alignment with user intentions.
Read critical files identified by agents and ask follow-up questions where needed.

### Phase 4: Final Plan
Goal: Write the final plan to the plan file.
Include critical file paths, concrete implementation steps, and an end-to-end verification section.

### Phase 5: Call plan_exit
At the end of planning, call plan_exit to request switching back to build mode.
Your turn should only end by either asking a question or calling plan_exit.

NOTE: Ask questions whenever intent is unclear. Avoid large assumptions.
</system-reminder>"""

    def _apply_mode_switch_metadata(self, metadata: Dict[str, Any]) -> None:
        mode_switch = metadata.get("mode_switch")
        if not isinstance(mode_switch, dict):
            return

        target_agent = mode_switch.get("to")
        if isinstance(target_agent, str) and target_agent:
            self.agent = target_agent

        synthetic_user = metadata.get("synthetic_user")
        if not isinstance(synthetic_user, dict):
            return

        text = synthetic_user.get("text")
        agent = synthetic_user.get("agent")
        if isinstance(text, str) and text.strip():
            self._pending_synthetic_users.append(
                {
                    "text": text.strip(),
                    "agent": str(agent or target_agent or self.agent),
                }
            )

    async def _flush_synthetic_users(self) -> None:
        from .session import Session

        pending = list(self._pending_synthetic_users)
        self._pending_synthetic_users.clear()
        if not pending:
            return

        for item in pending:
            text = item["text"]
            agent = item["agent"]
            self.messages.append({"role": "user", "content": text})
            user_msg = Message.create_user(
                message_id=Identifier.ascending("message"),
                session_id=self.session_id,
                text=text,
                created=int(time.time() * 1000),
                agent=agent,
                synthetic=True,
            )
            await Session.add_message(self.session_id, user_msg)

    async def _handle_direct_subagent_mention(
        self,
        user_message: str,
        agent_info: Any,
    ) -> Optional[str]:
        """Handle direct ``@subagent ...`` user invocation."""
        try:
            from ..agent import Agent, AgentMode
            from ..tool.task import TaskParams, extract_subagent_mention, short_description
        except Exception:
            return None

        parsed = extract_subagent_mention(user_message)
        if not parsed:
            return None

        subagent_name, prompt = parsed
        subagent = await Agent.get(subagent_name)
        if not subagent or subagent.mode != AgentMode.SUBAGENT:
            return None

        task_tool = ToolRegistry.get("task")
        if not task_tool:
            return None

        params = TaskParams(
            description=short_description(prompt),
            prompt=prompt,
            subagent_type=subagent_name,
        )
        ctx = ToolContext(
            session_id=self.session_id,
            message_id=Identifier.ascending("message"),
            agent=self.agent,
            call_id=Identifier.ascending("call"),
            extra={
                "cwd": self.cwd,
                "worktree": self.worktree,
                "provider_id": self.provider_id,
                "model_id": self.model_id,
                "bypass_agent_check": True,
            },
            _ruleset=(agent_info.permission if agent_info else []),
        )

        try:
            result = await task_tool.execute(params, ctx)
        except Exception as e:
            return f"Failed to run @{subagent_name}: {e}"
        content = result.output
        start_tag = "<task_result>"
        end_tag = "</task_result>"
        if start_tag in content and end_tag in content:
            inner = content.split(start_tag, 1)[1].split(end_tag, 1)[0].strip()
            if inner:
                return inner
        return content

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
                        await self._call_callback(on_tool_start, tc.name, tc.id, {})

                elif chunk.type == "tool_call_delta":
                    if chunk.tool_call_id and chunk.tool_call_id in current_tool_calls:
                        current_tool_calls[chunk.tool_call_id].input_json += chunk.tool_call_input_delta or ""

                elif chunk.type == "tool_call_end" and chunk.tool_call:
                    tc_id = chunk.tool_call.id
                    if tc_id in current_tool_calls:
                        tc = current_tool_calls[tc_id]
                        tc.input = chunk.tool_call.input
                        tc.status = "running"

                        # Notify with parsed input args
                        if on_tool_start:
                            await self._call_callback(on_tool_start, tc.name, tc.id, tc.input)

                        # Execute the tool
                        tool_result = await self._execute_tool(tc.name, tc.input)
                        tc.end_time = int(time.time() * 1000)

                        if tool_result.get("error"):
                            tc.status = "error"
                            tc.error = tool_result["error"]
                        else:
                            tc.status = "completed"
                            tc.output = tool_result.get("output", "")
                            tc.attachments = tool_result.get("attachments", [])
                            tc.metadata = dict(tool_result.get("metadata", {}) or {})
                            self._apply_mode_switch_metadata(tc.metadata)

                        result.tool_calls.append(tc)
                        if on_tool_end:
                            callback_metadata = dict(tool_result.get("metadata", {}))
                            if tc.attachments:
                                callback_metadata["attachments"] = tc.attachments
                            await self._call_callback(
                                on_tool_end, tc.name, tc.id, tc.output, tc.error,
                                tool_result.get("title", ""),
                                callback_metadata,
                            )

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
            # Check if it's an MCP tool
            try:
                from ..mcp import MCP
                mcp_tools = await MCP.tools()
                if tool_name in mcp_tools:
                    return await self._execute_mcp_tool(tool_name, mcp_tools[tool_name], tool_input)
            except Exception as e:
                log.error("MCP tool lookup failed", {"tool": tool_name, "error": str(e)})
            return {"error": f"Unknown tool: {tool_name}"}

        # Load agent permission ruleset
        agent_ruleset: List[Dict[str, Any]] = []
        try:
            from ..agent import Agent
            agent_info = await Agent.get(self.agent)
            if agent_info:
                agent_ruleset = agent_info.permission
        except Exception as e:
            log.warn("failed to load agent permissions", {"error": str(e)})

        try:
            await self._check_doom_loop(tool_name, tool_input, agent_ruleset)

            # Create tool context with permission ruleset
            ctx = ToolContext(
                session_id=self.session_id,
                message_id=Identifier.ascending("message"),
                agent=self.agent,
                call_id=Identifier.ascending("call"),
                extra={
                    "cwd": self.cwd,
                    "worktree": self.worktree,
                    "provider_id": self.provider_id,
                    "model_id": self.model_id,
                },
                messages=list(self.messages),
                _ruleset=agent_ruleset,
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
                "attachments": result.attachments,
            }

        except (RejectedError, CorrectedError, DeniedError) as e:
            log.info("permission error", {"tool": tool_name, "error": str(e)})
            return {"error": str(e)}
        except Exception as e:
            log.error("tool execution error", {"tool": tool_name, "error": str(e)})
            return {"error": str(e)}

    async def _check_doom_loop(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        agent_ruleset: List[Dict[str, Any]],
    ) -> None:
        signature = f"{tool_name}:{json.dumps(tool_input, sort_keys=True, default=str)}"
        self._recent_tool_signatures.append(signature)
        if len(self._recent_tool_signatures) > 50:
            self._recent_tool_signatures = self._recent_tool_signatures[-50:]

        if len(self._recent_tool_signatures) < DOOM_LOOP_THRESHOLD:
            return

        recent = self._recent_tool_signatures[-DOOM_LOOP_THRESHOLD:]
        if len(set(recent)) != 1:
            return

        from ..permission import Permission

        await Permission.ask(
            session_id=self.session_id,
            permission="doom_loop",
            patterns=[tool_name],
            ruleset=Permission.from_config_list(agent_ruleset),
            always=[tool_name],
            metadata={
                "tool": tool_name,
                "input": tool_input,
            },
        )

    async def _call_callback(self, callback: callable, *args) -> None:
        """Call a callback, handling both sync and async."""
        if asyncio.iscoroutinefunction(callback):
            await callback(*args)
        else:
            callback(*args)

    async def _execute_mcp_tool(
        self,
        tool_id: str,
        mcp_info: Dict[str, Any],
        tool_input: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a tool via MCP.

        Args:
            tool_id: The sanitized tool ID (client_name + tool_name)
            mcp_info: MCP tool info dict with 'client', 'name', 'timeout' keys
            tool_input: Tool input parameters

        Returns:
            Dict with output or error
        """
        from ..mcp import MCP

        client_name = mcp_info["client"]
        original_name = mcp_info["name"]

        state = await MCP._get_state()
        client = state.clients.get(client_name)
        if not client:
            return {"error": f"MCP client not connected: {client_name}"}

        try:
            timeout = mcp_info.get("timeout", 30.0)
            result = await asyncio.wait_for(
                client.call_tool(original_name, tool_input),
                timeout=timeout,
            )

            # Extract text from content blocks
            text_parts = []
            for content in (result.content or []):
                if hasattr(content, "text"):
                    text_parts.append(content.text)

            return {
                "output": "\n".join(text_parts) or "Tool completed",
                "title": "",
                "metadata": {},
            }
        except asyncio.TimeoutError:
            return {"error": f"MCP tool call timed out: {original_name}"}
        except Exception as e:
            log.error("MCP tool execution error", {
                "tool": original_name,
                "client": client_name,
                "error": str(e),
            })
            return {"error": str(e)}
