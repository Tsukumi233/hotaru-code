"""Shared callback adapters for streaming message parts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from .stream_parts import PartStreamBuilder


PartSink = Callable[[Dict[str, Any]], None]


@dataclass(frozen=True)
class PartCallbacks:
    """Typed callback bundle accepted by SessionPrompt.prompt."""

    on_text: Callable[[str], None]
    on_tool_update: Callable[[Dict[str, Any]], None]
    on_reasoning_start: Callable[[Optional[str], Optional[Dict[str, Any]]], Any]
    on_reasoning_delta: Callable[[Optional[str], str, Optional[Dict[str, Any]]], Any]
    on_reasoning_end: Callable[[Optional[str], Optional[Dict[str, Any]]], Any]
    on_step_start: Callable[[Optional[str]], None]
    on_step_finish: Callable[[str, Optional[str], Optional[Dict[str, Any]], float], None]
    on_patch: Callable[[Optional[str], Optional[list[str]]], None]


def create_part_callbacks(*, part_builder: PartStreamBuilder, on_part: PartSink) -> PartCallbacks:
    """Create shared part callbacks from a part sink."""

    def _emit(part: Optional[Dict[str, Any]]) -> None:
        if part:
            on_part(part)

    def on_text(text: str) -> None:
        _emit(part_builder.text_delta(text))

    def on_tool_update(tool_state: Dict[str, Any]) -> None:
        _emit(part_builder.tool_update(tool_state))

    async def on_reasoning_start(reasoning_id: Optional[str], metadata: Optional[Dict[str, Any]] = None) -> None:
        _emit(part_builder.reasoning_start(reasoning_id, metadata))

    async def on_reasoning_delta(
        reasoning_id: Optional[str],
        delta: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        _emit(part_builder.reasoning_delta(reasoning_id, delta, metadata))

    async def on_reasoning_end(reasoning_id: Optional[str], metadata: Optional[Dict[str, Any]] = None) -> None:
        _emit(part_builder.reasoning_end(reasoning_id, metadata))

    def on_step_start(snapshot: Optional[str]) -> None:
        _emit(part_builder.step_start(snapshot))

    def on_step_finish(
        reason: str,
        snapshot: Optional[str],
        tokens: Optional[Dict[str, Any]] = None,
        cost: float = 0.0,
    ) -> None:
        _emit(part_builder.step_finish(reason=reason, snapshot=snapshot, tokens=tokens, cost=cost))

    def on_patch(patch_hash: Optional[str], files_changed: Optional[list[str]] = None) -> None:
        _emit(part_builder.patch(patch_hash=patch_hash, files=files_changed))

    return PartCallbacks(
        on_text=on_text,
        on_tool_update=on_tool_update,
        on_reasoning_start=on_reasoning_start,
        on_reasoning_delta=on_reasoning_delta,
        on_reasoning_end=on_reasoning_end,
        on_step_start=on_step_start,
        on_step_finish=on_step_finish,
        on_patch=on_patch,
    )
