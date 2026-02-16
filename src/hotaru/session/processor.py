"""Session processor for handling LLM responses and tool execution."""

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

from ..core.id import Identifier
from ..permission import RejectedError, CorrectedError, DeniedError
from ..question.question import RejectedError as QuestionRejectedError
from ..provider.transform import ProviderTransform
from ..tool import ToolContext
from ..tool.registry import ToolRegistry
from ..util.log import Log
from .llm import LLM, StreamInput, StreamChunk

log = Log.create({"service": "session.processor"})

# Maximum consecutive identical tool calls before triggering doom loop detection
DOOM_LOOP_THRESHOLD = 3

_MAX_STEPS_PROMPT_PATH = Path(__file__).parent / "prompt" / "max-steps.txt"
_MAX_STEPS_PROMPT = _MAX_STEPS_PROMPT_PATH.read_text(encoding="utf-8").strip()
_BUILD_SWITCH_PROMPT_PATH = Path(__file__).parent / "prompt" / "build-switch.txt"
_BUILD_SWITCH_PROMPT = _BUILD_SWITCH_PROMPT_PATH.read_text(encoding="utf-8").strip()
_PLAN_REMINDER_PROMPT_PATH = Path(__file__).parent / "prompt" / "plan-reminder.txt"
_PLAN_REMINDER_PROMPT = _PLAN_REMINDER_PROMPT_PATH.read_text(encoding="utf-8").strip()
_STRUCTURED_OUTPUT_TOOL = "StructuredOutput"


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
    title: Optional[str] = None
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
    stop_reason: Optional[str] = None
    structured_output: Optional[Any] = None
    reasoning_text: str = ""


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
        sync_agent_from_session: bool = True,
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
        self._sync_agent_from_session_enabled = bool(sync_agent_from_session)
        self.turn = 0
        self.messages: List[Dict[str, Any]] = []
        self.tool_calls: Dict[str, ToolCallState] = {}
        self._recent_tool_signatures: List[str] = []
        self._pending_synthetic_users: List[Dict[str, str]] = []
        self._last_assistant_agent: Optional[str] = None
        self._allowed_tools: Optional[Set[str]] = None
        self._structured_output: Optional[Any] = None
        self._continue_loop_on_deny = False
        self._interleaved_field: Optional[str] = None
        self._interleaved_field_resolved: bool = False

    async def load_history(self) -> None:
        """Load prior conversation history from persisted messages.

        Converts stored structured messages into the OpenAI-format
        message list that the LLM expects. Must be called before
        ``process()`` when resuming an existing session.
        """
        from .session import Session
        from .message_store import filter_compacted, to_model_messages

        stored_structured = await Session.messages(session_id=self.session_id)
        filtered = filter_compacted(stored_structured)
        interleaved_field = await self._resolve_interleaved_field()
        self.messages = to_model_messages(filtered, interleaved_field=interleaved_field)

        for msg in reversed(filtered):
            if msg.info.role != "assistant":
                continue
            if msg.info.agent:
                self._last_assistant_agent = msg.info.agent
            break
        log.info("loaded history", {
            "session_id": self.session_id,
            "message_count": len(self.messages),
            "source": "message_store",
        })

    async def _resolve_interleaved_field(self) -> Optional[str]:
        """Resolve interleaved reasoning field from the active model."""
        if self._interleaved_field_resolved:
            return self._interleaved_field

        self._interleaved_field_resolved = True
        try:
            from ..provider import Provider

            model = await Provider.get_model(self.provider_id, self.model_id)
            self._interleaved_field = ProviderTransform.interleaved_field(model)
        except Exception as e:
            self._interleaved_field = None
            log.debug("failed to resolve interleaved field", {"error": str(e)})
        return self._interleaved_field

    async def process(
        self,
        user_message: str,
        system_prompt: Optional[str] = None,
        on_text: Optional[callable] = None,
        on_tool_start: Optional[callable] = None,
        on_tool_end: Optional[callable] = None,
        on_tool_update: Optional[callable] = None,
        on_reasoning_start: Optional[callable] = None,
        on_reasoning_delta: Optional[callable] = None,
        on_reasoning_end: Optional[callable] = None,
    ) -> ProcessorResult:
        """Compatibility entrypoint that runs the full loop."""
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
                    on_tool_update=on_tool_update,
                    on_reasoning_start=on_reasoning_start,
                    on_reasoning_delta=on_reasoning_delta,
                    on_reasoning_end=on_reasoning_end,
                ),
            )

        self.add_user_message(user_message)
        try:
            from ..core.config import ConfigManager

            config = await ConfigManager.get()
            self._continue_loop_on_deny = bool(getattr(config, "continue_loop_on_deny", False))
        except Exception as e:
            self._continue_loop_on_deny = False
            log.debug("failed to read continue_loop_on_deny", {"error": str(e)})
        direct_subagent_result = await self.try_direct_subagent_mention(user_message)
        if direct_subagent_result is not None:
            self.messages.append({"role": "assistant", "content": direct_subagent_result})
            return ProcessorResult(status="stop", text=direct_subagent_result)

        result = ProcessorResult(status="continue")
        while result.status == "continue":
            turn_result = await self.process_step(
                system_prompt=system_prompt,
                on_text=on_text,
                on_tool_start=on_tool_start,
                on_tool_end=on_tool_end,
                on_tool_update=on_tool_update,
                on_reasoning_start=on_reasoning_start,
                on_reasoning_delta=on_reasoning_delta,
                on_reasoning_end=on_reasoning_end,
            )
            result.text += turn_result.text
            result.tool_calls.extend(turn_result.tool_calls)
            for key, value in (turn_result.usage or {}).items():
                result.usage[key] = result.usage.get(key, 0) + value
            if turn_result.error:
                result.status = "error"
                result.error = turn_result.error
                break
            result.status = turn_result.status
            if result.status != "continue":
                break
        return result

    def add_user_message(self, user_message: str) -> None:
        """Append a user message to in-memory model history."""
        self.messages.append({"role": "user", "content": user_message})

    async def try_direct_subagent_mention(self, user_message: str) -> Optional[str]:
        """Run direct @subagent dispatch if the user explicitly invoked one."""
        from ..agent import Agent

        await self._sync_agent_from_session()
        agent_info = await Agent.get(self.agent)
        return await self._handle_direct_subagent_mention(user_message, agent_info)

    async def process_step(
        self,
        *,
        system_prompt: Optional[Union[str, List[str]]] = None,
        on_text: Optional[callable] = None,
        on_tool_start: Optional[callable] = None,
        on_tool_end: Optional[callable] = None,
        on_tool_update: Optional[callable] = None,
        on_reasoning_start: Optional[callable] = None,
        on_reasoning_delta: Optional[callable] = None,
        on_reasoning_end: Optional[callable] = None,
        tool_definitions: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        retries: int = 0,
        assistant_message_id: Optional[str] = None,
    ) -> ProcessorResult:
        """Process exactly one assistant turn.

        This is the single-turn primitive used by SessionPrompt.loop.
        """
        from ..agent import Agent

        if self.turn >= self.max_turns:
            return ProcessorResult(
                status="error",
                error=f"Maximum turns ({self.max_turns}) exceeded",
            )

        self.turn += 1
        try:
            from ..core.config import ConfigManager

            config = await ConfigManager.get()
            self._continue_loop_on_deny = bool(getattr(config, "continue_loop_on_deny", False))
        except Exception as e:
            self._continue_loop_on_deny = False
            log.debug("failed to read continue_loop_on_deny", {"error": str(e)})
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

        max_steps = agent_info.steps if agent_info else None
        is_last_step = bool(max_steps is not None and self.turn >= max_steps)

        if tool_definitions is not None:
            effective_tools = list(tool_definitions)
        else:
            effective_tools: List[Dict[str, Any]] = []
            if not is_last_step:
                effective_tools = await ToolRegistry.get_tool_definitions(
                    caller_agent=self.agent,
                    provider_id=self.provider_id,
                    model_id=self.model_id,
                )

            if not is_last_step:
                try:
                    from ..mcp import MCP

                    mcp_tools = await MCP.tools()
                    for tool_id, tool_info in mcp_tools.items():
                        schema = dict(tool_info.get("input_schema") or {})
                        schema.setdefault("type", "object")
                        schema["additionalProperties"] = False
                        effective_tools.append(
                            {
                                "type": "function",
                                "function": {
                                    "name": tool_id,
                                    "description": tool_info.get("description", ""),
                                    "parameters": schema,
                                },
                            }
                        )
                except asyncio.CancelledError as e:
                    # Some MCP client transports may surface connection failures as
                    # CancelledError. Treat that as MCP unavailable instead of
                    # cancelling the whole assistant turn.
                    log.warn("failed to load MCP tools", {"error": str(e)})
                except Exception as e:
                    log.warn("failed to load MCP tools", {"error": str(e)})

            if not is_last_step:
                try:
                    from ..permission import Permission

                    if agent_info and agent_info.permission:
                        ruleset = Permission.from_config_list(agent_info.permission)
                        tool_names = [d["function"]["name"] for d in effective_tools]
                        disabled = Permission.disabled_tools(tool_names, ruleset)
                        if disabled:
                            log.info("filtering disabled tools", {"disabled": list(disabled)})
                            effective_tools = [d for d in effective_tools if d["function"]["name"] not in disabled]
                except Exception as e:
                    log.warn("failed to filter disabled tools", {"error": str(e)})

        if is_last_step:
            effective_tools = []

        self._allowed_tools = {
            str(item.get("function", {}).get("name"))
            for item in effective_tools
            if isinstance(item, dict) and isinstance(item.get("function"), dict) and item["function"].get("name")
        } or None
        self._structured_output = None

        await self._insert_mode_reminders(
            current_agent=self.agent,
            previous_assistant_agent=self._last_assistant_agent,
        )
        messages_for_turn = self.messages.copy()
        if is_last_step:
            messages_for_turn.append(
                {
                    "role": "assistant",
                    "content": _MAX_STEPS_PROMPT,
                }
            )

        stream_input = StreamInput(
            session_id=self.session_id,
            model_id=self.model_id,
            provider_id=self.provider_id,
            messages=messages_for_turn,
            system=system_prompt,
            tools=effective_tools if effective_tools else None,
            tool_choice=tool_choice if effective_tools else None,
            retries=int(retries or 0),
            max_tokens=4096,
            temperature=agent_info.temperature if agent_info else None,
            top_p=agent_info.top_p if agent_info else None,
            options=(agent_info.options or None) if agent_info else None,
            variant=agent_info.variant if agent_info else None,
        )

        turn_result = await self._process_turn(
            stream_input,
            on_text=on_text,
            on_tool_start=on_tool_start,
            on_tool_end=on_tool_end,
            on_tool_update=on_tool_update,
            on_reasoning_start=on_reasoning_start,
            on_reasoning_delta=on_reasoning_delta,
            on_reasoning_end=on_reasoning_end,
            assistant_message_id=assistant_message_id,
        )
        if turn_result.error:
            turn_result.status = "error"
            return turn_result

        if self._structured_output is not None:
            turn_result.structured_output = self._structured_output
            turn_result.status = "stop"
            self._last_assistant_agent = assistant_agent_for_turn
            return turn_result

        self._last_assistant_agent = assistant_agent_for_turn
        if not turn_result.tool_calls:
            turn_result.status = "stop"
            return turn_result

        interleaved_field = await self._resolve_interleaved_field()

        assistant_message: Dict[str, Any] = {"role": "assistant"}
        assistant_message["content"] = turn_result.text if turn_result.text else None
        assistant_message["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": json.dumps(tc.input)},
            }
            for tc in turn_result.tool_calls
        ]
        if interleaved_field and turn_result.reasoning_text:
            assistant_message[interleaved_field] = turn_result.reasoning_text
        self.messages.append(assistant_message)

        for tc in turn_result.tool_calls:
            self.messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tc.output if tc.status == "completed" else tc.error or "Tool execution failed",
                }
            )

        if self._pending_synthetic_users:
            await self._flush_synthetic_users()

        if turn_result.status != "stop":
            turn_result.status = "continue"
        return turn_result

    def last_assistant_agent(self) -> str:
        """Return the agent name used for the latest assistant turn."""
        return self._last_assistant_agent or self.agent

    async def _sync_agent_from_session(self) -> None:
        if not self._sync_agent_from_session_enabled:
            return
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
        return _PLAN_REMINDER_PROMPT.replace("{plan_info}", plan_info)

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
        from .message_store import MessageInfo, MessageTime, ModelRef, PartTime, TextPart

        pending = list(self._pending_synthetic_users)
        self._pending_synthetic_users.clear()
        if not pending:
            return

        now_ms = int(time.time() * 1000)
        for item in pending:
            text = item["text"]
            agent = item["agent"]
            message_id = Identifier.ascending("message")
            self.messages.append({"role": "user", "content": text})
            await Session.update_message(
                MessageInfo(
                    id=message_id,
                    session_id=self.session_id,
                    role="user",
                    agent=agent,
                    model=ModelRef(provider_id=self.provider_id, model_id=self.model_id),
                    time=MessageTime(created=now_ms, completed=now_ms),
                )
            )
            await Session.update_part(
                TextPart(
                    id=Identifier.ascending("part"),
                    session_id=self.session_id,
                    message_id=message_id,
                    text=text,
                    synthetic=True,
                    time=PartTime(start=now_ms, end=now_ms),
                )
            )

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

    @staticmethod
    def _tool_update_payload(tc: ToolCallState) -> Dict[str, Any]:
        return {
            "id": tc.id,
            "name": tc.name,
            "input_json": tc.input_json,
            "input": dict(tc.input or {}),
            "status": tc.status,
            "output": tc.output,
            "error": tc.error,
            "title": tc.title,
            "metadata": dict(tc.metadata or {}),
            "attachments": list(tc.attachments or []),
            "start_time": tc.start_time,
            "end_time": tc.end_time,
        }

    async def _emit_tool_update(self, callback: Optional[callable], tc: ToolCallState) -> None:
        if not callback:
            return
        await self._call_callback(callback, self._tool_update_payload(tc))

    async def _process_turn(
        self,
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
        """Process a single turn of the conversation.

        Args:
            stream_input: Input for the LLM stream
            on_text: Callback for text chunks
            on_tool_start: Callback when tool starts
            on_tool_end: Callback when tool ends
            on_tool_update: Callback when a tool state changes
            on_reasoning_start: Callback when reasoning block starts
            on_reasoning_delta: Callback when reasoning delta arrives
            on_reasoning_end: Callback when reasoning block ends

        Returns:
            ProcessorResult for this turn
        """
        result = ProcessorResult(status="continue")
        current_tool_calls: Dict[str, ToolCallState] = {}
        blocked = False
        reasoning_fragments: List[str] = []

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
                    await self._emit_tool_update(on_tool_update, tc)

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
                        await self._emit_tool_update(on_tool_update, tc)

                        # Execute the tool
                        tool_result = await self._execute_tool(
                            tc.name,
                            tc.input,
                            tc=tc,
                            on_tool_update=on_tool_update,
                            assistant_message_id=assistant_message_id,
                        )
                        tc.end_time = int(time.time() * 1000)

                        if tool_result.get("error"):
                            tc.status = "error"
                            tc.error = tool_result["error"]
                            if tool_result.get("blocked") and not self._continue_loop_on_deny:
                                blocked = True
                        else:
                            tc.status = "completed"
                            tc.output = tool_result.get("output", "")
                            tc.title = str(tool_result.get("title") or "") or None
                            tc.attachments = tool_result.get("attachments", [])
                            tc.metadata = dict(tool_result.get("metadata", {}) or {})
                            self._apply_mode_switch_metadata(tc.metadata)
                        await self._emit_tool_update(on_tool_update, tc)

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
                        if blocked:
                            result.status = "stop"
                            break

                elif chunk.type == "reasoning_start":
                    if on_reasoning_start:
                        await self._call_callback(
                            on_reasoning_start,
                            chunk.reasoning_id,
                            dict(chunk.provider_metadata or {}),
                        )

                elif chunk.type == "reasoning_delta":
                    piece = str(chunk.reasoning_text or "")
                    if piece:
                        reasoning_fragments.append(piece)
                    if on_reasoning_delta:
                        await self._call_callback(
                            on_reasoning_delta,
                            chunk.reasoning_id,
                            piece,
                            dict(chunk.provider_metadata or {}),
                        )

                elif chunk.type == "reasoning_end":
                    if on_reasoning_end:
                        await self._call_callback(
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
            log.error("turn processing error", {"error": str(e)})
            result.status = "error"
            result.error = str(e)

        result.reasoning_text = "".join(reasoning_fragments)
        return result

    async def _execute_tool(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        *,
        tc: Optional[ToolCallState] = None,
        on_tool_update: Optional[callable] = None,
        assistant_message_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute a tool.

        Args:
            tool_name: Name of the tool
            tool_input: Tool input parameters

        Returns:
            Dict with output or error
        """
        if self._allowed_tools is not None and tool_name not in self._allowed_tools:
            return {"error": f"Unknown tool: {tool_name}"}

        if tool_name == _STRUCTURED_OUTPUT_TOOL:
            if not self._allowed_tools or tool_name not in self._allowed_tools:
                return {"error": f"Unknown tool: {tool_name}"}
            self._structured_output = dict(tool_input or {})
            return {
                "output": "Structured output captured successfully.",
                "title": "Structured Output",
                "metadata": {"valid": True},
            }

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

        # Load agent + session permission rulesets.
        merged_ruleset: List[Dict[str, Any]] = []
        try:
            from ..agent import Agent
            from .session import Session

            agent_info = await Agent.get(self.agent)
            if agent_info and agent_info.permission:
                merged_ruleset.extend(agent_info.permission)

            session = await Session.get(self.session_id)
            session_permission = getattr(session, "permission", None) if session else None
            if isinstance(session_permission, list):
                merged_ruleset.extend(session_permission)
        except Exception as e:
            log.warn("failed to load agent permissions", {"error": str(e)})

        pending_tasks: List[asyncio.Task[Any]] = []

        def _handle_metadata_update(snapshot: Dict[str, Any]) -> None:
            if tc is None:
                return
            title = snapshot.get("title")
            tc.title = str(title) if isinstance(title, str) and title else tc.title
            tc.metadata = {
                key: value
                for key, value in snapshot.items()
                if key != "title"
            }
            if on_tool_update:
                pending_tasks.append(
                    asyncio.create_task(self._emit_tool_update(on_tool_update, tc))
                )

        try:
            await self._check_doom_loop(tool_name, tool_input, merged_ruleset)

            # Create tool context with permission ruleset
            ctx = ToolContext(
                session_id=self.session_id,
                message_id=assistant_message_id or Identifier.ascending("message"),
                agent=self.agent,
                call_id=(tc.id if tc and tc.id else Identifier.ascending("call")),
                extra={
                    "cwd": self.cwd,
                    "worktree": self.worktree,
                    "provider_id": self.provider_id,
                    "model_id": self.model_id,
                },
                messages=list(self.messages),
                _on_metadata=_handle_metadata_update,
                _ruleset=merged_ruleset,
            )

            # Validate and parse input
            try:
                args = tool.parameters_type.model_validate(tool_input)
            except Exception as e:
                return {"error": f"Invalid tool input: {e}"}

            # Execute the tool
            result = await tool.execute(args, ctx)
            if pending_tasks:
                await asyncio.gather(*pending_tasks, return_exceptions=True)

            raw_metadata = dict(ctx._metadata or {})
            raw_metadata.update(dict(result.metadata or {}))
            title = str(result.title or raw_metadata.pop("title", "") or "")
            if title:
                raw_metadata["title"] = title

            return {
                "output": result.output,
                "title": title,
                "metadata": raw_metadata,
                "attachments": result.attachments,
            }

        except (RejectedError, CorrectedError) as e:
            if pending_tasks:
                await asyncio.gather(*pending_tasks, return_exceptions=True)
            log.info("permission error", {"tool": tool_name, "error": str(e)})
            return {"error": str(e), "blocked": True}
        except DeniedError as e:
            if pending_tasks:
                await asyncio.gather(*pending_tasks, return_exceptions=True)
            log.info("permission denied by ruleset", {"tool": tool_name, "error": str(e)})
            return {"error": str(e)}
        except QuestionRejectedError as e:
            if pending_tasks:
                await asyncio.gather(*pending_tasks, return_exceptions=True)
            log.info("question rejected", {"tool": tool_name, "error": str(e)})
            return {"error": str(e), "blocked": True}
        except Exception as e:
            if pending_tasks:
                await asyncio.gather(*pending_tasks, return_exceptions=True)
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
