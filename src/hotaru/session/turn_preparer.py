"""Turn preparation for session processor."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

from ..tool.resolver import ToolResolver
from .llm import StreamInput

_MAX_STEPS_PROMPT_PATH = Path(__file__).parent / "prompt" / "max-steps.txt"
_MAX_STEPS_PROMPT = _MAX_STEPS_PROMPT_PATH.read_text(encoding="utf-8").strip()


@dataclass
class PreparedTurn:
    stream_input: StreamInput
    assistant_agent_for_turn: str
    allowed_tools: Optional[Set[str]]
    is_last_step: bool


class TurnPreparer:
    """Resolve turn config and build stream input."""

    async def load_continue_loop_on_deny(self) -> bool:
        try:
            from ..core.config import ConfigManager

            config = await ConfigManager.get()
            return bool(config.continue_loop_on_deny)
        except Exception:
            return False

    async def prepare(
        self,
        *,
        session_id: str,
        model_id: str,
        provider_id: str,
        agent: str,
        turn: int,
        max_turns: int,
        messages: List[Dict[str, Any]],
        system_prompt: Optional[Union[str, List[str]]] = None,
        tool_definitions: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        retries: int = 0,
    ) -> PreparedTurn:
        from ..agent import Agent

        agent_info = await Agent.get(agent)
        assistant_agent_for_turn = agent

        max_steps = agent_info.steps if agent_info else None
        is_last_step = bool(max_steps is not None and turn >= max_steps)

        if tool_definitions is not None:
            effective_tools = list(tool_definitions)
        else:
            effective_tools = []
            if not is_last_step:
                rules = list(agent_info.permission) if agent_info and agent_info.permission else None
                effective_tools = await ToolResolver.resolve(
                    caller_agent=agent,
                    provider_id=provider_id,
                    model_id=model_id,
                    permission_rules=rules,
                )

        if is_last_step:
            effective_tools = []

        allowed_tools = {
            str(item.get("function", {}).get("name"))
            for item in effective_tools
            if isinstance(item, dict) and isinstance(item.get("function"), dict) and item["function"].get("name")
        } or None

        messages_for_turn = list(messages)
        if is_last_step:
            messages_for_turn.append(
                {
                    "role": "assistant",
                    "content": _MAX_STEPS_PROMPT,
                }
            )

        stream_input = StreamInput(
            session_id=session_id,
            model_id=model_id,
            provider_id=provider_id,
            messages=messages_for_turn,
            system=system_prompt,
            tools=effective_tools if effective_tools else None,
            tool_choice=tool_choice if effective_tools else None,
            retries=int(retries or 0),
            max_tokens=None,
            temperature=agent_info.temperature if agent_info else None,
            top_p=agent_info.top_p if agent_info else None,
            options=(agent_info.options or None) if agent_info else None,
            variant=agent_info.variant if agent_info else None,
        )

        return PreparedTurn(
            stream_input=stream_input,
            assistant_agent_for_turn=assistant_agent_for_turn,
            allowed_tools=allowed_tools,
            is_last_step=is_last_step,
        )
