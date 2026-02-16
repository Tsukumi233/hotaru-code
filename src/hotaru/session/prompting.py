"""Session prompt loop.

Bridges persisted session messages and the step-based processor loop.
Persists structured message records.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..agent import Agent
from ..core.context import ContextNotFoundError
from ..core.id import Identifier
from ..project import Instance
from ..provider import Provider
from ..provider.provider import ProcessedModelInfo
from ..snapshot import SnapshotTracker
from ..tool.registry import ToolRegistry
from ..util.log import Log
from .compaction import SessionCompaction
from .message_store import (
    CompactionPart,
    MessageInfo,
    MessageTime,
    ModelRef,
    PatchPart,
    PartTime,
    PathInfo,
    ReasoningPart,
    StepFinishPart,
    StepStartPart,
    TextPart,
    TokenUsage,
    ToolPart,
    ToolState,
    ToolStateTime,
)
from .processor import ProcessorResult, SessionProcessor, ToolCallState
from .session import Session
from .summary import SessionSummary

log = Log.create({"service": "session.prompt"})

_COMPACTION_USER_TEXT = "What did we do so far?"
_CONTINUE_USER_TEXT = (
    "Continue if you have next steps, or stop and ask for clarification if you are unsure how to proceed."
)
_STRUCTURED_OUTPUT_DESCRIPTION = """Use this tool to return your final response in the requested structured format.

IMPORTANT:
- You MUST call this tool exactly once at the end of your response
- The input must be valid JSON matching the required schema
- Complete all necessary research and tool calls BEFORE calling this tool
- This tool provides your final answer - no further actions are taken after calling it"""
_STRUCTURED_OUTPUT_TOOL = "StructuredOutput"


@dataclass
class PromptResult:
    """Result wrapper for SessionPrompt prompt/loop APIs."""

    result: ProcessorResult
    assistant_message_id: str
    user_message_id: str
    text: str


def _now_ms() -> int:
    return int(time.time() * 1000)


def _usage_to_tokens(usage: Dict[str, int]) -> TokenUsage:
    input_tokens = int(usage.get("input_tokens", usage.get("input", 0)) or 0)
    output_tokens = int(usage.get("output_tokens", usage.get("output", 0)) or 0)
    reasoning_tokens = int(usage.get("reasoning_tokens", usage.get("reasoning", 0)) or 0)
    cache_read_tokens = int(usage.get("cache_read_tokens", usage.get("cache_read", 0)) or 0)
    cache_write_tokens = int(usage.get("cache_write_tokens", usage.get("cache_write", 0)) or 0)
    total = int(usage.get("total_tokens", 0) or 0)
    if total <= 0:
        total = input_tokens + output_tokens + reasoning_tokens + cache_read_tokens + cache_write_tokens
    return TokenUsage(
        input=input_tokens,
        output=output_tokens,
        reasoning=reasoning_tokens,
        cache_read=cache_read_tokens,
        cache_write=cache_write_tokens,
        total=total,
    )


def _accumulate_usage(total: Dict[str, int], delta: Dict[str, int]) -> None:
    for key, value in (delta or {}).items():
        total[key] = int(total.get(key, 0) or 0) + int(value or 0)


def _usage_cost(*, tokens: TokenUsage, model: Optional[ProcessedModelInfo]) -> float:
    if not model:
        return 0.0
    pricing = model.cost
    input_cost = float(tokens.input or 0) * float(pricing.input or 0) / 1_000_000
    output_cost = float(tokens.output or 0) * float(pricing.output or 0) / 1_000_000
    cache_read_cost = float(tokens.cache_read or 0) * float(pricing.cache_read or 0) / 1_000_000
    cache_write_cost = float(tokens.cache_write or 0) * float(pricing.cache_write or 0) / 1_000_000
    # Follow existing OpenCode behavior: reasoning billed with output rate.
    reasoning_cost = float(tokens.reasoning or 0) * float(pricing.output or 0) / 1_000_000
    return max(input_cost + output_cost + cache_read_cost + cache_write_cost + reasoning_cost, 0.0)


def _step_finish_reason(step: ProcessorResult) -> str:
    if step.stop_reason:
        return str(step.stop_reason)
    if step.error:
        return "error"
    if step.status == "continue":
        if step.tool_calls:
            return "tool-calls"
        return "continue"
    if step.status in {"stop", "error"}:
        return step.status
    return "unknown"


def _normalize_finish_reason(reason: Optional[str]) -> Optional[str]:
    if not reason:
        return None
    value = str(reason).strip().lower()
    if value in {"tool_calls", "tool-call", "tool_call", "tool-calls"}:
        return "tool-calls"
    if value in {"stop", "length", "content_filter", "unknown"}:
        return value
    return "unknown"


async def _latest_user_id(session_id: str) -> Optional[str]:
    structured = await Session.messages(session_id=session_id)
    for msg in reversed(structured):
        if msg.info.role == "user":
            return msg.info.id
    return None


async def _persist_user_message(
    *,
    session_id: str,
    message_id: str,
    content: str,
    agent: str,
    provider_id: str,
    model_id: str,
    synthetic: bool = False,
    write_structured_info: bool = True,
    output_format: Optional[Dict[str, Any]] = None,
) -> None:
    now = _now_ms()
    if write_structured_info:
        await Session.update_message(
            MessageInfo(
                id=message_id,
                session_id=session_id,
                role="user",
                agent=agent,
                model=ModelRef(provider_id=provider_id, model_id=model_id),
                format=dict(output_format) if output_format else None,
                time=MessageTime(created=now, completed=now),
            )
        )
    await Session.update_part(
        TextPart(
            id=Identifier.ascending("part"),
            session_id=session_id,
            message_id=message_id,
            text=content,
            synthetic=synthetic,
            time=PartTime(start=now, end=now),
        )
    )


async def _persist_assistant_message(
    *,
    session_id: str,
    message_id: str,
    parent_id: Optional[str],
    text: str,
    tool_calls: list[ToolCallState],
    usage: Dict[str, int],
    agent: str,
    provider_id: str,
    model_id: str,
    cwd: str,
    worktree: str,
    mode: Optional[str] = None,
    summary: bool = False,
    error: Optional[str] = None,
    structured_output: Optional[Any] = None,
    cost: float = 0.0,
    finish_reason: Optional[str] = None,
) -> None:
    now = _now_ms()
    tokens_structured = _usage_to_tokens(usage)

    finish = _normalize_finish_reason(finish_reason) or ("tool-calls" if tool_calls else "stop")
    if error:
        finish = "unknown"
    await Session.update_message(
        MessageInfo(
            id=message_id,
            session_id=session_id,
            role="assistant",
            parent_id=parent_id,
            agent=agent,
            mode=mode or agent,
            model=ModelRef(provider_id=provider_id, model_id=model_id),
            time=MessageTime(created=now, completed=now),
            finish=finish,
            error={"message": error} if error else None,
            cost=float(cost or 0.0),
            tokens=tokens_structured,
            path=PathInfo(cwd=cwd, root=worktree),
            summary=True if summary else None,
            structured=structured_output,
        )
    )
    if text:
        await Session.update_part(
            TextPart(
                id=Identifier.ascending("part"),
                session_id=session_id,
                message_id=message_id,
                text=text,
                time=PartTime(start=now, end=now),
            )
        )
    for tc in tool_calls:
        await Session.update_part(
            ToolPart(
                id=Identifier.ascending("part"),
                session_id=session_id,
                message_id=message_id,
                tool=tc.name,
                call_id=tc.id,
                state=ToolState(
                    status="completed" if tc.status == "completed" else "error",
                    input=dict(tc.input or {}),
                    raw=str(tc.input_json or ""),
                    output=tc.output,
                    error=tc.error,
                    title=str(tc.title or (tc.metadata or {}).get("title", "")) or None,
                    metadata=dict(tc.metadata or {}),
                    attachments=list(tc.attachments or []),
                    time=ToolStateTime(
                        start=int(tc.start_time or now),
                        end=int(tc.end_time or now),
                    ),
                ),
            )
        )


@dataclass
class _CompactionRun:
    summary_assistant_id: str
    usage: Dict[str, int]
    auto_continued: bool
    continue_user_id: Optional[str] = None
    error: Optional[str] = None


@dataclass(frozen=True)
class _PendingCompaction:
    user_id: str
    auto: bool


class SessionPrompt:
    """High-level session prompt loop."""

    @classmethod
    async def prompt(
        cls,
        *,
        session_id: str,
        content: str,
        format: Optional[Dict[str, Any]] = None,
        provider_id: str,
        model_id: str,
        agent: str,
        cwd: str,
        worktree: str,
        system_prompt: Optional[str] = None,
        on_text: Optional[Callable[..., Any]] = None,
        on_tool_start: Optional[Callable[..., Any]] = None,
        on_tool_end: Optional[Callable[..., Any]] = None,
        on_tool_update: Optional[Callable[..., Any]] = None,
        resume_history: bool = True,
        assistant_message_id: Optional[str] = None,
        auto_compaction: bool = True,
    ) -> PromptResult:
        """Persist user input, then run the processing loop."""

        async def _run() -> PromptResult:
            session = await Session.get(session_id)
            if not session:
                raise ValueError(f"Session not found: {session_id}")

            if (
                session.agent != agent
                or session.model_id != model_id
                or session.provider_id != provider_id
            ):
                await Session.update(
                    session_id,
                    project_id=session.project_id,
                    agent=agent,
                    model_id=model_id,
                    provider_id=provider_id,
                )

            user_message_id = Identifier.ascending("message")
            await _persist_user_message(
                session_id=session_id,
                message_id=user_message_id,
                content=content,
                agent=agent,
                provider_id=provider_id,
                model_id=model_id,
                output_format=format,
            )

            # Best-effort session title.
            try:
                await SessionSummary.summarize(session_id=session_id, message_id=user_message_id)
            except Exception as e:
                log.debug("title summary failed", {"error": str(e)})

            return await cls.loop(
                session_id=session_id,
                provider_id=provider_id,
                model_id=model_id,
                agent=agent,
                cwd=cwd,
                worktree=worktree,
                system_prompt=system_prompt,
                on_text=on_text,
                on_tool_start=on_tool_start,
                on_tool_end=on_tool_end,
                on_tool_update=on_tool_update,
                resume_history=resume_history,
                initial_user_content=content,
                user_message_id=user_message_id,
                output_format=format,
                assistant_message_id=assistant_message_id,
                auto_compaction=auto_compaction,
            )

        try:
            current_dir = Instance.directory()
        except ContextNotFoundError:
            current_dir = None

        if current_dir is None or Path(current_dir).resolve() != Path(cwd).resolve():
            return await Instance.provide(directory=cwd, fn=_run)
        return await _run()

    @classmethod
    async def loop(
        cls,
        *,
        session_id: str,
        provider_id: str,
        model_id: str,
        agent: str,
        cwd: str,
        worktree: str,
        output_format: Optional[Dict[str, Any]] = None,
        system_prompt: Optional[str] = None,
        on_text: Optional[Callable[..., Any]] = None,
        on_tool_start: Optional[Callable[..., Any]] = None,
        on_tool_end: Optional[Callable[..., Any]] = None,
        on_tool_update: Optional[Callable[..., Any]] = None,
        resume_history: bool = True,
        initial_user_content: Optional[str] = None,
        user_message_id: Optional[str] = None,
        assistant_message_id: Optional[str] = None,
        auto_compaction: bool = True,
    ) -> PromptResult:
        """Run outer loop by repeatedly calling processor.process_step."""
        processor = SessionProcessor(
            session_id=session_id,
            model_id=model_id,
            provider_id=provider_id,
            agent=agent,
            cwd=cwd,
            worktree=worktree,
        )

        if resume_history:
            await processor.load_history()
        elif initial_user_content is not None:
            processor.add_user_message(initial_user_content)

        direct_result: Optional[str] = None
        if initial_user_content is not None:
            direct_result = await processor.try_direct_subagent_mention(initial_user_content)
        if direct_result is not None:
            parent_id = await _latest_user_id(session_id) or user_message_id
            final_assistant_id = assistant_message_id or Identifier.ascending("message")
            assistant_agent = processor.last_assistant_agent()
            await _persist_assistant_message(
                session_id=session_id,
                message_id=final_assistant_id,
                parent_id=parent_id,
                text=direct_result,
                tool_calls=[],
                usage={},
                agent=assistant_agent,
                provider_id=provider_id,
                model_id=model_id,
                cwd=cwd,
                worktree=worktree,
                mode=assistant_agent,
            )
            result = ProcessorResult(status="stop", text=direct_result)
            return PromptResult(
                result=result,
                assistant_message_id=final_assistant_id,
                user_message_id=str(user_message_id or ""),
                text=direct_result,
            )

        aggregate = ProcessorResult(status="continue", text="", usage={})
        final_assistant_id = ""
        first_assistant = True
        current_user_id = user_message_id or await _latest_user_id(session_id)

        main_model: Optional[ProcessedModelInfo] = None
        try:
            main_model = await Provider.get_model(provider_id, model_id)
        except Exception as e:
            log.warn("failed to resolve model for usage/cost checks", {"error": str(e)})
            main_model = None

        while aggregate.status == "continue":
            pending_compaction = await cls._pending_compaction(session_id=session_id)
            if pending_compaction is not None:
                compaction = await cls._run_compaction(
                    processor=processor,
                    session_id=session_id,
                    agent=agent,
                    provider_id=provider_id,
                    model_id=model_id,
                    cwd=cwd,
                    worktree=worktree,
                    system_prompt=system_prompt,
                    auto=pending_compaction.auto,
                    compaction_user_id=pending_compaction.user_id,
                    create_request=False,
                    append_prompt_to_memory=False,
                )
                final_assistant_id = compaction.summary_assistant_id or final_assistant_id
                _accumulate_usage(aggregate.usage, compaction.usage)

                if compaction.error:
                    aggregate.status = "error"
                    aggregate.error = compaction.error
                    break

                current_user_id = compaction.continue_user_id or current_user_id
                aggregate.status = "continue" if compaction.auto_continued else "stop"
                continue

            resolved_tools = await cls.resolve_tools(
                session_id=session_id,
                agent_name=processor.agent,
                provider_id=provider_id,
                model_id=model_id,
                output_format=output_format,
            )
            assistant_id_for_turn = (
                assistant_message_id if first_assistant and assistant_message_id else Identifier.ascending("message")
            )
            tool_choice: Optional[Dict[str, Any] | str] = None
            if output_format and output_format.get("type") == "json_schema":
                tool_choice = "required"

            step, step_tokens, step_cost = await cls._process_step_with_tracking(
                processor=processor,
                session_id=session_id,
                model_info=main_model,
                cwd=cwd,
                worktree=worktree,
                system_prompt=system_prompt,
                on_text=on_text,
                on_tool_start=on_tool_start,
                on_tool_end=on_tool_end,
                on_tool_update=on_tool_update,
                tool_definitions=resolved_tools,
                tool_choice=tool_choice,
                retries=2,
                assistant_message_id=assistant_id_for_turn,
            )

            parent_id = current_user_id
            first_assistant = False
            assistant_agent = processor.last_assistant_agent()
            await _persist_assistant_message(
                session_id=session_id,
                message_id=assistant_id_for_turn,
                parent_id=parent_id,
                text=step.text,
                tool_calls=step.tool_calls,
                usage=step.usage,
                agent=assistant_agent,
                provider_id=provider_id,
                model_id=model_id,
                cwd=cwd,
                worktree=worktree,
                mode=assistant_agent,
                error=step.error,
                structured_output=step.structured_output,
                cost=step_cost,
                finish_reason=step.stop_reason,
            )
            final_assistant_id = assistant_id_for_turn

            # process_step persists assistant/tool records in-memory only when tools were called.
            if not step.tool_calls:
                processor.messages.append({"role": "assistant", "content": step.text or None})

            aggregate.text += step.text
            aggregate.tool_calls.extend(step.tool_calls)
            if step.structured_output is not None:
                if step.text:
                    aggregate.text = step.text
                else:
                    aggregate.text = json.dumps(step.structured_output, ensure_ascii=False)
            _accumulate_usage(aggregate.usage, step.usage)

            if step.error:
                aggregate.status = "error"
                aggregate.error = step.error
                break

            if step.status != "continue":
                if output_format and output_format.get("type") == "json_schema":
                    if step.structured_output is None and not step.error:
                        aggregate.status = "error"
                        aggregate.error = "Model did not produce structured output"
                        break
                aggregate.status = step.status
                break

            should_compact = False
            if auto_compaction and main_model is not None:
                try:
                    should_compact = await SessionCompaction.is_overflow(
                        tokens=step_tokens,
                        model=main_model,
                    )
                except Exception as e:
                    log.warn("compaction overflow check failed", {"error": str(e)})

            if not should_compact:
                current_user_id = await _latest_user_id(session_id) or current_user_id
                aggregate.status = "continue"
                continue

            compaction = await cls._run_compaction(
                processor=processor,
                session_id=session_id,
                agent=agent,
                provider_id=provider_id,
                model_id=model_id,
                cwd=cwd,
                worktree=worktree,
                system_prompt=system_prompt,
                auto=True,
                compaction_user_id=None,
                create_request=True,
                append_prompt_to_memory=True,
            )
            final_assistant_id = compaction.summary_assistant_id or final_assistant_id
            _accumulate_usage(aggregate.usage, compaction.usage)

            if compaction.error:
                aggregate.status = "error"
                aggregate.error = compaction.error
                break

            current_user_id = compaction.continue_user_id or current_user_id
            aggregate.status = "continue" if compaction.auto_continued else "stop"

        try:
            await SessionCompaction.prune(session_id=session_id)
        except Exception as e:
            log.debug("compaction prune skipped", {"error": str(e)})

        return PromptResult(
            result=aggregate,
            assistant_message_id=final_assistant_id,
            user_message_id=str(user_message_id or ""),
            text=aggregate.text,
        )

    @classmethod
    async def _process_step_with_tracking(
        cls,
        *,
        processor: SessionProcessor,
        session_id: str,
        model_info: Optional[ProcessedModelInfo],
        cwd: str,
        worktree: str,
        system_prompt: Optional[str],
        on_text: Optional[Callable[..., Any]],
        on_tool_start: Optional[Callable[..., Any]],
        on_tool_end: Optional[Callable[..., Any]],
        on_tool_update: Optional[Callable[..., Any]],
        tool_definitions: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Dict[str, Any] | str] = None,
        retries: int = 0,
        assistant_message_id: str,
    ) -> tuple[ProcessorResult, TokenUsage, float]:
        step_start_snapshot: Optional[str] = None
        try:
            step_start_snapshot = await SnapshotTracker.track(
                session_id=session_id,
                cwd=cwd,
                worktree=worktree,
            )
        except Exception as e:
            log.debug("step snapshot start failed", {"error": str(e)})

        try:
            await Session.update_part(
                StepStartPart(
                    id=Identifier.ascending("part"),
                    session_id=session_id,
                    message_id=assistant_message_id,
                    snapshot=step_start_snapshot,
                )
            )
        except Exception as e:
            log.debug("failed to persist step-start", {"error": str(e)})

        reasoning_parts: Dict[str, Dict[str, Any]] = {}
        fallback_index = 0
        anonymous_reasoning_key: Optional[str] = None

        def _reasoning_key(raw_id: Optional[str], *, create: bool = True) -> str:
            nonlocal fallback_index
            nonlocal anonymous_reasoning_key
            value = str(raw_id or "").strip()
            if value:
                return value
            if anonymous_reasoning_key:
                return anonymous_reasoning_key
            if not create:
                return ""
            fallback_index += 1
            anonymous_reasoning_key = f"reasoning_{fallback_index}"
            return anonymous_reasoning_key

        async def _close_reasoning(reasoning_id: str, metadata: Optional[Dict[str, Any]] = None) -> None:
            nonlocal anonymous_reasoning_key
            state = reasoning_parts.get(reasoning_id)
            if not state:
                return
            if state.get("closed"):
                return
            state["closed"] = True
            if isinstance(metadata, dict) and metadata:
                state["metadata"] = dict(metadata)
            now = _now_ms()
            try:
                await Session.update_part(
                    ReasoningPart(
                        id=state["part_id"],
                        session_id=session_id,
                        message_id=assistant_message_id,
                        text=str(state.get("text", "")).rstrip(),
                        time=PartTime(
                            start=int(state.get("start") or now),
                            end=now,
                        ),
                        metadata=dict(state.get("metadata") or {}) or None,
                    )
                )
            except Exception as e:
                log.debug("failed to close reasoning part", {"error": str(e)})
            if reasoning_id == anonymous_reasoning_key:
                anonymous_reasoning_key = None

        async def _on_reasoning_start(reasoning_id: Optional[str], metadata: Optional[Dict[str, Any]] = None) -> None:
            key = _reasoning_key(reasoning_id)
            if key in reasoning_parts:
                return
            now = _now_ms()
            state = {
                "part_id": Identifier.ascending("part"),
                "text": "",
                "start": now,
                "metadata": dict(metadata or {}) if isinstance(metadata, dict) else {},
                "closed": False,
            }
            reasoning_parts[key] = state
            try:
                await Session.update_part(
                    ReasoningPart(
                        id=state["part_id"],
                        session_id=session_id,
                        message_id=assistant_message_id,
                        text="",
                        time=PartTime(start=now),
                        metadata=dict(state["metadata"] or {}) or None,
                    )
                )
            except Exception as e:
                log.debug("failed to persist reasoning start", {"error": str(e)})

        async def _on_reasoning_delta(
            reasoning_id: Optional[str],
            delta: str,
            metadata: Optional[Dict[str, Any]] = None,
        ) -> None:
            key = _reasoning_key(reasoning_id)
            if key not in reasoning_parts:
                await _on_reasoning_start(reasoning_id=key, metadata=metadata)
            state = reasoning_parts.get(key)
            if not state:
                return
            if isinstance(metadata, dict) and metadata:
                state["metadata"] = dict(metadata)
            piece = str(delta or "")
            if not piece:
                return
            state["text"] = str(state.get("text", "")) + piece
            try:
                await Session.update_part_delta(
                    session_id=session_id,
                    message_id=assistant_message_id,
                    part_id=state["part_id"],
                    field="text",
                    delta=piece,
                )
            except Exception as e:
                log.debug("failed to persist reasoning delta", {"error": str(e)})

        async def _on_reasoning_end(reasoning_id: Optional[str], metadata: Optional[Dict[str, Any]] = None) -> None:
            key = _reasoning_key(reasoning_id, create=False)
            if not key:
                return
            await _close_reasoning(key, metadata=metadata)

        try:
            step = await processor.process_step(
                system_prompt=system_prompt,
                on_text=on_text,
                on_tool_start=on_tool_start,
                on_tool_end=on_tool_end,
                on_tool_update=on_tool_update,
                on_reasoning_start=_on_reasoning_start,
                on_reasoning_delta=_on_reasoning_delta,
                on_reasoning_end=_on_reasoning_end,
                tool_definitions=tool_definitions,
                tool_choice=tool_choice,
                retries=retries,
                assistant_message_id=assistant_message_id,
            )
        except Exception as e:
            log.error("step processing failed", {"error": str(e)})
            step = ProcessorResult(status="error", error=str(e))

        for rid in list(reasoning_parts.keys()):
            await _close_reasoning(rid)

        tokens = _usage_to_tokens(step.usage)
        cost = _usage_cost(tokens=tokens, model=model_info)
        step_end_snapshot: Optional[str] = None
        try:
            step_end_snapshot = await SnapshotTracker.track(
                session_id=session_id,
                cwd=cwd,
                worktree=worktree,
            )
        except Exception as e:
            log.debug("step snapshot end failed", {"error": str(e)})

        try:
            await Session.update_part(
                StepFinishPart(
                    id=Identifier.ascending("part"),
                    session_id=session_id,
                    message_id=assistant_message_id,
                    reason=_step_finish_reason(step),
                    snapshot=step_end_snapshot,
                    cost=cost,
                    tokens=tokens,
                )
            )
        except Exception as e:
            log.debug("failed to persist step-finish", {"error": str(e)})

        if step_start_snapshot:
            try:
                patch = await SnapshotTracker.patch(
                    session_id=session_id,
                    base_hash=step_start_snapshot,
                    cwd=cwd,
                    worktree=worktree,
                )
                if patch.files:
                    await Session.update_part(
                        PatchPart(
                            id=Identifier.ascending("part"),
                            session_id=session_id,
                            message_id=assistant_message_id,
                            hash=patch.hash,
                            files=patch.files,
                        )
                    )
            except Exception as e:
                log.debug("failed to persist step patch", {"error": str(e)})

        return step, tokens, cost

    @classmethod
    async def resolve_tools(
        cls,
        *,
        session_id: str,
        agent_name: str,
        provider_id: str,
        model_id: str,
        output_format: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        tools = await ToolRegistry.get_tool_definitions(
            caller_agent=agent_name,
            provider_id=provider_id,
            model_id=model_id,
        )
        try:
            from ..mcp import MCP

            mcp_tools = await MCP.tools()
            for tool_id, tool_info in mcp_tools.items():
                schema = dict(tool_info.get("input_schema") or {})
                schema.setdefault("type", "object")
                schema["additionalProperties"] = False
                tools.append(
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
            log.warn("failed to load MCP tools", {"error": str(e)})
        except Exception as e:
            log.warn("failed to load MCP tools", {"error": str(e)})

        try:
            from ..permission import Permission

            agent_info = await Agent.get(agent_name)
            session = await Session.get(session_id)
            merged_rules = []
            if agent_info and agent_info.permission:
                merged_rules.extend(agent_info.permission)
            session_rules = getattr(session, "permission", None) if session else None
            if isinstance(session_rules, list):
                merged_rules.extend(session_rules)

            if merged_rules:
                ruleset = Permission.from_config_list(merged_rules)
                tool_names = [
                    str(item.get("function", {}).get("name"))
                    for item in tools
                    if isinstance(item, dict) and isinstance(item.get("function"), dict)
                ]
                disabled = Permission.disabled_tools(tool_names, ruleset)
                if disabled:
                    tools = [item for item in tools if item.get("function", {}).get("name") not in disabled]
        except Exception as e:
            log.warn("failed to resolve tool permissions", {"error": str(e)})

        if output_format and output_format.get("type") == "json_schema":
            schema = dict(output_format.get("schema") or {})
            schema.pop("$schema", None)
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": _STRUCTURED_OUTPUT_TOOL,
                        "description": _STRUCTURED_OUTPUT_DESCRIPTION,
                        "parameters": schema or {"type": "object", "properties": {}},
                    },
                }
            )
        return tools

    @classmethod
    async def _run_compaction(
        cls,
        *,
        processor: SessionProcessor,
        session_id: str,
        agent: str,
        provider_id: str,
        model_id: str,
        cwd: str,
        worktree: str,
        system_prompt: Optional[str],
        auto: bool,
        compaction_user_id: Optional[str],
        create_request: bool,
        append_prompt_to_memory: bool,
    ) -> _CompactionRun:
        effective_compaction_user_id = compaction_user_id or Identifier.ascending("message")
        if create_request:
            await SessionCompaction.create(
                session_id=session_id,
                agent=agent,
                provider_id=provider_id,
                model_id=model_id,
                auto=auto,
                message_id=effective_compaction_user_id,
            )
            await _persist_user_message(
                session_id=session_id,
                message_id=effective_compaction_user_id,
                content=_COMPACTION_USER_TEXT,
                agent=agent,
                provider_id=provider_id,
                model_id=model_id,
                synthetic=True,
                write_structured_info=False,
            )
        if append_prompt_to_memory:
            processor.messages.append({"role": "user", "content": _COMPACTION_USER_TEXT})

        compact_agent_name = await SessionCompaction.compact_agent_name()
        compact_agent = await Agent.get(compact_agent_name)
        compact_provider_id = provider_id
        compact_model_id = model_id
        if compact_agent and compact_agent.model:
            compact_provider_id = compact_agent.model.provider_id
            compact_model_id = compact_agent.model.model_id

        compact_system_prompt = system_prompt
        if compact_agent and compact_agent.prompt:
            compact_system_prompt = (
                f"{compact_agent.prompt}\n\n{system_prompt}" if system_prompt else compact_agent.prompt
            )

        compact_processor = SessionProcessor(
            session_id=session_id,
            model_id=compact_model_id,
            provider_id=compact_provider_id,
            agent=compact_agent_name,
            cwd=cwd,
            worktree=worktree,
            max_turns=8,
            sync_agent_from_session=False,
        )
        compact_processor.messages = list(processor.messages)

        compact_model: Optional[ProcessedModelInfo] = None
        try:
            compact_model = await Provider.get_model(compact_provider_id, compact_model_id)
        except Exception as e:
            log.warn("failed to resolve compaction model for usage/cost", {"error": str(e)})
            compact_model = None

        summary_id = Identifier.ascending("message")
        result, _tokens, step_cost = await cls._process_step_with_tracking(
            processor=compact_processor,
            session_id=session_id,
            model_info=compact_model,
            cwd=cwd,
            worktree=worktree,
            system_prompt=compact_system_prompt,
            on_text=None,
            on_tool_start=None,
            on_tool_end=None,
            on_tool_update=None,
            retries=0,
            assistant_message_id=summary_id,
        )

        await _persist_assistant_message(
            session_id=session_id,
            message_id=summary_id,
            parent_id=effective_compaction_user_id,
            text=result.text,
            tool_calls=result.tool_calls,
            usage=result.usage,
            agent=compact_agent_name,
            provider_id=compact_provider_id,
            model_id=compact_model_id,
            cwd=cwd,
            worktree=worktree,
            mode="compaction",
            summary=True,
            error=result.error,
            cost=step_cost,
            finish_reason=result.stop_reason,
        )

        if result.error:
            return _CompactionRun(
                summary_assistant_id=summary_id,
                usage=dict(result.usage or {}),
                auto_continued=False,
                error=result.error,
            )

        # Keep only compressed context in-memory for subsequent turns.
        processor.messages = [{"role": "assistant", "content": result.text or ""}]

        if auto:
            continue_user_id = Identifier.ascending("message")
            await _persist_user_message(
                session_id=session_id,
                message_id=continue_user_id,
                content=_CONTINUE_USER_TEXT,
                agent=agent,
                provider_id=provider_id,
                model_id=model_id,
                synthetic=True,
            )
            processor.messages.append({"role": "user", "content": _CONTINUE_USER_TEXT})
            return _CompactionRun(
                summary_assistant_id=summary_id,
                usage=dict(result.usage or {}),
                auto_continued=True,
                continue_user_id=continue_user_id,
            )

        return _CompactionRun(
            summary_assistant_id=summary_id,
            usage=dict(result.usage or {}),
            auto_continued=False,
        )

    @classmethod
    async def _pending_compaction(cls, *, session_id: str) -> Optional[_PendingCompaction]:
        messages = await Session.messages(session_id=session_id)
        if not messages:
            return None

        summarized_user_ids = {
            msg.info.parent_id
            for msg in messages
            if msg.info.role == "assistant" and msg.info.summary is True and bool(msg.info.finish) and msg.info.parent_id
        }
        summarized_user_ids = {item for item in summarized_user_ids if item}

        for msg in reversed(messages):
            if msg.info.role != "user":
                continue
            compaction = next((part for part in msg.parts if isinstance(part, CompactionPart)), None)
            if compaction is None:
                continue
            if msg.info.id in summarized_user_ids:
                continue
            return _PendingCompaction(user_id=msg.info.id, auto=bool(compaction.auto))
        return None
