"""Agent/mode transition helpers for session processor."""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from ..core.id import Identifier
from ..tool import ToolContext

if TYPE_CHECKING:
    from ..runtime import AppContext

_BUILD_SWITCH_PROMPT_PATH = Path(__file__).parent / "prompt" / "build-switch.txt"
_BUILD_SWITCH_PROMPT = _BUILD_SWITCH_PROMPT_PATH.read_text(encoding="utf-8").strip()
_PLAN_REMINDER_PROMPT_PATH = Path(__file__).parent / "prompt" / "plan-reminder.txt"
_PLAN_REMINDER_PROMPT = _PLAN_REMINDER_PROMPT_PATH.read_text(encoding="utf-8").strip()


class AgentFlow:
    """Manage agent synchronization and mode transitions."""

    async def sync_agent_from_session(
        self,
        *,
        session_id: str,
        agent: str,
        enabled: bool,
    ) -> str:
        if not enabled:
            return agent

        from .session import Session

        session = await Session.get(session_id)
        if session and session.agent:
            return str(session.agent)
        return agent

    async def insert_mode_reminders(
        self,
        *,
        messages: List[Dict[str, Any]],
        session_id: str,
        worktree: str,
        current_agent: str,
        previous_assistant_agent: Optional[str],
    ) -> None:
        from .session import Session

        if current_agent != "plan" and previous_assistant_agent != "plan":
            return

        session = await Session.get(session_id)
        if not session:
            return

        plan_path = Session.plan_path_for(
            session,
            worktree=worktree,
            is_git=bool(worktree and worktree != "/"),
        )

        if current_agent != "plan" and previous_assistant_agent == "plan":
            if Path(plan_path).exists():
                self._append_reminder_to_latest_user(
                    messages,
                    _BUILD_SWITCH_PROMPT
                    + "\n\n"
                    + f"A plan file exists at {plan_path}. You should execute on the plan defined within it",
                )
            return

        if current_agent == "plan" and previous_assistant_agent != "plan":
            exists = Path(plan_path).exists()
            if not exists:
                Path(plan_path).parent.mkdir(parents=True, exist_ok=True)
            self._append_reminder_to_latest_user(
                messages,
                self.build_plan_mode_reminder(plan_path=plan_path, exists=exists),
            )

    @staticmethod
    def _append_reminder_to_latest_user(messages: List[Dict[str, Any]], reminder: str) -> None:
        for message in reversed(messages):
            if message.get("role") != "user":
                continue

            content = str(message.get("content") or "")
            if reminder in content:
                return
            message["content"] = f"{content.rstrip()}\n\n{reminder}" if content.strip() else reminder
            return

    @staticmethod
    def build_plan_mode_reminder(*, plan_path: str, exists: bool) -> str:
        plan_info = (
            f"A plan file already exists at {plan_path}. You can read it and make incremental edits using the edit tool."
            if exists
            else f"No plan file exists yet. You should create your plan at {plan_path} using the write tool."
        )
        return _PLAN_REMINDER_PROMPT.replace("{plan_info}", plan_info)

    @staticmethod
    def apply_mode_switch_metadata(
        *,
        metadata: Dict[str, Any],
        current_agent: str,
        pending_synthetic_users: List[Dict[str, str]],
    ) -> str:
        mode_switch = metadata.get("mode_switch")
        if not isinstance(mode_switch, dict):
            return current_agent

        target_agent = mode_switch.get("to")
        next_agent = current_agent
        if isinstance(target_agent, str) and target_agent:
            next_agent = target_agent

        synthetic_user = metadata.get("synthetic_user")
        if not isinstance(synthetic_user, dict):
            return next_agent

        text = synthetic_user.get("text")
        agent = synthetic_user.get("agent")
        if isinstance(text, str) and text.strip():
            pending_synthetic_users.append(
                {
                    "text": text.strip(),
                    "agent": str(agent or target_agent or next_agent),
                }
            )
        return next_agent

    async def flush_synthetic_users(
        self,
        *,
        pending_synthetic_users: List[Dict[str, str]],
        messages: List[Dict[str, Any]],
        session_id: str,
        provider_id: str,
        model_id: str,
    ) -> None:
        from .message_store import MessageInfo, MessageTime, ModelRef, PartTime, TextPart
        from .session import Session

        pending = list(pending_synthetic_users)
        pending_synthetic_users.clear()
        if not pending:
            return

        now_ms = int(time.time() * 1000)
        for item in pending:
            text = item["text"]
            agent = item["agent"]
            message_id = Identifier.ascending("message")
            messages.append({"role": "user", "content": text})
            await Session.update_message(
                MessageInfo(
                    id=message_id,
                    session_id=session_id,
                    role="user",
                    agent=agent,
                    model=ModelRef(provider_id=provider_id, model_id=model_id),
                    time=MessageTime(created=now_ms, completed=now_ms),
                )
            )
            await Session.update_part(
                TextPart(
                    id=Identifier.ascending("part"),
                    session_id=session_id,
                    message_id=message_id,
                    text=text,
                    synthetic=True,
                    time=PartTime(start=now_ms, end=now_ms),
                )
            )

    async def handle_direct_subagent_mention(
        self,
        *,
        app: AppContext,
        user_message: str,
        session_id: str,
        agent: str,
        cwd: str,
        worktree: str,
        provider_id: str,
        model_id: str,
        agent_info: Any,
    ) -> Optional[str]:
        try:
            from ..agent import Agent, AgentMode
            from ..tool.task import TaskParams, extract_subagent_mention, short_description
        except Exception:
            return None

        parsed = extract_subagent_mention(user_message)
        if not parsed:
            return None

        subagent_name, prompt = parsed
        subagent = await app.agents.get(subagent_name)
        if not subagent or subagent.mode != AgentMode.SUBAGENT:
            return None

        if not app.tools.get("task"):
            return None

        params = TaskParams(
            description=short_description(prompt),
            prompt=prompt,
            subagent_type=subagent_name,
        )
        ctx = ToolContext(
            app=app,
            session_id=session_id,
            message_id=Identifier.ascending("message"),
            agent=agent,
            call_id=Identifier.ascending("call"),
            extra={
                "cwd": cwd,
                "worktree": worktree,
                "provider_id": provider_id,
                "model_id": model_id,
                "bypass_agent_check": True,
            },
            _ruleset=(agent_info.permission if agent_info else []),
        )

        try:
            result = await app.tools.execute("task", params, ctx)
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
