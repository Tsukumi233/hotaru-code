"""Session processor orchestrating LLM turns and tool execution."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

from ..provider.transform import ProviderTransform
from ..tool.registry import ToolRegistry
from ..tool.resolver import ToolResolver
from ..util.log import Log
from .agent_flow import AgentFlow
from .doom_loop import DoomLoopDetector
from .history_loader import HistoryLoader
from .llm import StreamInput
from .processor_types import ProcessorResult, ToolCallState
from .retry import SessionRetry
from .tool_executor import ToolExecutor
from .turn_preparer import TurnPreparer
from .turn_runner import TurnRunner

try:
    from openai import APIConnectionError as OpenAIAPIConnectionError
    from openai import APIError as OpenAIAPIError
    from openai import APIStatusError as OpenAIAPIStatusError
    from openai import APITimeoutError as OpenAIAPITimeoutError
    from openai import RateLimitError as OpenAIRateLimitError
except ImportError:
    OpenAIAPIConnectionError = None
    OpenAIAPIError = None
    OpenAIAPIStatusError = None
    OpenAIAPITimeoutError = None
    OpenAIRateLimitError = None

try:
    from anthropic import APIConnectionError as AnthropicAPIConnectionError
    from anthropic import APIError as AnthropicAPIError
    from anthropic import APIStatusError as AnthropicAPIStatusError
    from anthropic import APITimeoutError as AnthropicAPITimeoutError
    from anthropic import RateLimitError as AnthropicRateLimitError
except ImportError:
    AnthropicAPIConnectionError = None
    AnthropicAPIError = None
    AnthropicAPIStatusError = None
    AnthropicAPITimeoutError = None
    AnthropicRateLimitError = None

log = Log.create({"service": "session.processor"})

DOOM_LOOP_THRESHOLD = 3
_STRUCTURED_OUTPUT_TOOL = "StructuredOutput"

_RECOVERABLE_TURN_ERRORS = tuple(
    value
    for value in (
        TimeoutError,
        asyncio.TimeoutError,
        OpenAIAPIError,
        OpenAIAPIConnectionError,
        OpenAIAPIStatusError,
        OpenAIAPITimeoutError,
        OpenAIRateLimitError,
        AnthropicAPIError,
        AnthropicAPIConnectionError,
        AnthropicAPIStatusError,
        AnthropicAPITimeoutError,
        AnthropicRateLimitError,
    )
    if isinstance(value, type)
)


class SessionProcessor:
    """Processor for handling LLM responses and tool execution."""

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
        *,
        history: Optional[HistoryLoader] = None,
        agentflow: Optional[AgentFlow] = None,
        turnprep: Optional[TurnPreparer] = None,
        turnrun: Optional[TurnRunner] = None,
        tools: Optional[ToolExecutor] = None,
        doom: Optional[DoomLoopDetector] = None,
    ):
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
        self._continue_loop_on_deny = False

        self.history = history or HistoryLoader()
        self.agentflow = agentflow or AgentFlow()
        self.turnprep = turnprep or TurnPreparer()
        self.doom = doom or DoomLoopDetector(
            session_id=self.session_id,
            threshold=DOOM_LOOP_THRESHOLD,
            window=50,
            signatures=self._recent_tool_signatures,
        )
        self.tools = tools or ToolExecutor(
            session_id=self.session_id,
            model_id=self.model_id,
            provider_id=self.provider_id,
            cwd=self.cwd,
            worktree=self.worktree,
            doom=self.doom,
            emit_tool_update=self._emit_tool_update,
            execute_mcp=lambda **kwargs: self._execute_mcp_tool(**kwargs),
        )
        self.turnrun = turnrun or TurnRunner(
            call_callback=self._call_callback,
            emit_tool_update=self._emit_tool_update,
            execute_tool=self._execute_tool_via_executor,
            apply_mode_switch_metadata=self._apply_mode_switch_metadata,
            recoverable_error=self._recoverable_turn_error,
            continue_loop_on_deny=lambda: self._continue_loop_on_deny,
        )

    async def load_history(self) -> None:
        messages, last_assistant = await self.history.load(session_id=self.session_id)
        self.messages = messages
        if last_assistant:
            self._last_assistant_agent = last_assistant

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
        from ..core.context import ContextNotFoundError
        from ..project import Instance

        current_instance_dir: Optional[str]
        try:
            current_instance_dir = Instance.directory()
        except ContextNotFoundError:
            current_instance_dir = None

        if current_instance_dir is None or Path(current_instance_dir).resolve() != Path(self.cwd).resolve():
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
        self._continue_loop_on_deny = await self.turnprep.load_continue_loop_on_deny()

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
        self.messages.append({"role": "user", "content": user_message})

    async def try_direct_subagent_mention(self, user_message: str) -> Optional[str]:
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
        if self.turn >= self.max_turns:
            return ProcessorResult(
                status="error",
                error=f"Maximum turns ({self.max_turns}) exceeded",
            )

        self.turn += 1
        self._continue_loop_on_deny = await self.turnprep.load_continue_loop_on_deny()
        await self._sync_agent_from_session()

        log.info(
            "processing turn",
            {
                "turn": self.turn,
                "session_id": self.session_id,
                "agent": self.agent,
            },
        )

        await self._insert_mode_reminders(
            current_agent=self.agent,
            previous_assistant_agent=self._last_assistant_agent,
        )

        prepared = await self.turnprep.prepare(
            session_id=self.session_id,
            model_id=self.model_id,
            provider_id=self.provider_id,
            agent=self.agent,
            turn=self.turn,
            max_turns=self.max_turns,
            messages=self.messages,
            system_prompt=system_prompt,
            tool_definitions=tool_definitions,
            tool_choice=tool_choice,
            retries=retries,
        )

        self._allowed_tools = prepared.allowed_tools
        self.tools.reset_turn()

        turn_result = await self._process_turn(
            prepared.stream_input,
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

        if self.tools.structured_output is not None:
            turn_result.structured_output = self.tools.structured_output
            turn_result.status = "stop"
            self._last_assistant_agent = prepared.assistant_agent_for_turn
            return turn_result

        self._last_assistant_agent = prepared.assistant_agent_for_turn
        if not turn_result.tool_calls:
            turn_result.status = "stop"
            return turn_result

        self.messages.append(
            ProviderTransform.assistant_tool_message(
                text=turn_result.text,
                reasoning_text=turn_result.reasoning_text,
                tool_calls=[
                    {
                        "id": tc.id,
                        "name": tc.name,
                        "input": tc.input,
                    }
                    for tc in turn_result.tool_calls
                ],
            )
        )

        for tc in turn_result.tool_calls:
            self.messages.append(
                ProviderTransform.tool_result_message(
                    tool_call_id=tc.id,
                    status=tc.status,
                    output=tc.output,
                    error=tc.error,
                )
            )

        if self._pending_synthetic_users:
            await self._flush_synthetic_users()

        if turn_result.status != "stop":
            turn_result.status = "continue"
        return turn_result

    def last_assistant_agent(self) -> str:
        return self._last_assistant_agent or self.agent

    async def _sync_agent_from_session(self) -> None:
        self.agent = await self.agentflow.sync_agent_from_session(
            session_id=self.session_id,
            agent=self.agent,
            enabled=self._sync_agent_from_session_enabled,
        )

    async def _insert_mode_reminders(
        self,
        *,
        current_agent: str,
        previous_assistant_agent: Optional[str],
    ) -> None:
        await self.agentflow.insert_mode_reminders(
            messages=self.messages,
            session_id=self.session_id,
            worktree=self.worktree,
            current_agent=current_agent,
            previous_assistant_agent=previous_assistant_agent,
        )

    def _build_plan_mode_reminder(self, *, plan_path: str, exists: bool) -> str:
        return self.agentflow.build_plan_mode_reminder(plan_path=plan_path, exists=exists)

    def _apply_mode_switch_metadata(self, metadata: Dict[str, Any]) -> None:
        self.agent = self.agentflow.apply_mode_switch_metadata(
            metadata=metadata,
            current_agent=self.agent,
            pending_synthetic_users=self._pending_synthetic_users,
        )

    async def _flush_synthetic_users(self) -> None:
        await self.agentflow.flush_synthetic_users(
            pending_synthetic_users=self._pending_synthetic_users,
            messages=self.messages,
            session_id=self.session_id,
            provider_id=self.provider_id,
            model_id=self.model_id,
        )

    async def _handle_direct_subagent_mention(
        self,
        user_message: str,
        agent_info: Any,
    ) -> Optional[str]:
        return await self.agentflow.handle_direct_subagent_mention(
            user_message=user_message,
            session_id=self.session_id,
            agent=self.agent,
            cwd=self.cwd,
            worktree=self.worktree,
            provider_id=self.provider_id,
            model_id=self.model_id,
            agent_info=agent_info,
        )

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
        return await self.turnrun.run(
            stream_input=stream_input,
            on_text=on_text,
            on_tool_start=on_tool_start,
            on_tool_end=on_tool_end,
            on_tool_update=on_tool_update,
            on_reasoning_start=on_reasoning_start,
            on_reasoning_delta=on_reasoning_delta,
            on_reasoning_end=on_reasoning_end,
            assistant_message_id=assistant_message_id,
        )

    @staticmethod
    def _recoverable_turn_error(error: Exception) -> bool:
        if isinstance(error, _RECOVERABLE_TURN_ERRORS):
            return True
        return SessionRetry.retryable(error)

    async def _execute_tool_via_executor(self, **kwargs: Any) -> Dict[str, Any]:
        return await self._execute_tool(**kwargs)

    async def _execute_tool(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        *,
        tc: Optional[ToolCallState] = None,
        on_tool_update: Optional[callable] = None,
        assistant_message_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if self._allowed_tools is not None and tool_name not in self._allowed_tools:
            return {"error": f"Unknown tool: {tool_name}"}

        if tool_name != _STRUCTURED_OUTPUT_TOOL and not ToolRegistry.get(tool_name):
            mcp_info = await ToolResolver.mcp_info(tool_name)
            if mcp_info:
                return await self._execute_mcp_tool(
                    tool_id=tool_name,
                    mcp_info=mcp_info,
                    tool_input=tool_input,
                )
            return {"error": f"Unknown tool: {tool_name}"}

        return await self.tools.execute(
            tool_name=tool_name,
            tool_input=tool_input,
            allowed_tools=self._allowed_tools,
            messages=self.messages,
            agent=self.agent,
            tc=tc,
            on_tool_update=on_tool_update,
            assistant_message_id=assistant_message_id,
        )

    async def _check_doom_loop(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        agent_ruleset: List[Dict[str, Any]],
    ) -> None:
        await self.doom.check(
            tool_name=tool_name,
            tool_input=tool_input,
            ruleset=agent_ruleset,
        )

    async def _call_callback(self, callback: callable, *args: Any) -> None:
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
        return await self.tools.execute_mcp_tool(
            tool_id=tool_id,
            mcp_info=mcp_info,
            tool_input=tool_input,
        )
