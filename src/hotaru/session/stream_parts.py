"""Helpers for shaping callback-based stream updates into ordered message parts."""

from typing import Any, Dict, Optional

from ..core.id import Identifier


class PartStreamBuilder:
    """Build ordered part updates from text/tool/reasoning callbacks."""

    def __init__(self, session_id: str, message_id: str) -> None:
        self._session_id = session_id
        self._message_id = message_id
        self._part_id_counter = 0
        self._segment_text = ""
        self._current_text_part_id = self._next_part_id()
        self._tool_part_ids: Dict[str, str] = {}
        self._reasoning_parts: Dict[str, Dict[str, Any]] = {}
        self._fallback_reasoning_index = 0
        self._anonymous_reasoning_key: Optional[str] = None

    def _next_part_id(self) -> str:
        self._part_id_counter += 1
        return f"part-{self._part_id_counter}"

    def _split_text_segment(self) -> None:
        if not self._segment_text:
            return
        self._segment_text = ""
        self._current_text_part_id = self._next_part_id()

    def _tool_part_id(self, tool_id: str) -> str:
        existing = self._tool_part_ids.get(tool_id)
        if existing:
            return existing
        generated = self._next_part_id()
        self._tool_part_ids[tool_id] = generated
        return generated

    def _reasoning_key(self, raw_id: Optional[str], *, create: bool = True) -> str:
        value = str(raw_id or "").strip()
        if value:
            return value
        if self._anonymous_reasoning_key:
            return self._anonymous_reasoning_key
        if not create:
            return ""
        self._fallback_reasoning_index += 1
        self._anonymous_reasoning_key = f"reasoning_{self._fallback_reasoning_index}"
        return self._anonymous_reasoning_key

    def _new_reasoning_state(self, key: str, metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        self._split_text_segment()
        state = {
            "id": self._next_part_id(),
            "text": "",
            "metadata": dict(metadata or {}) if isinstance(metadata, dict) else {},
        }
        self._reasoning_parts[key] = state
        return state

    def text_delta(self, delta: str) -> Optional[Dict[str, Any]]:
        piece = str(delta or "")
        if not piece:
            return None
        self._segment_text += piece
        return {
            "id": self._current_text_part_id,
            "session_id": self._session_id,
            "message_id": self._message_id,
            "type": "text",
            "text": self._segment_text,
        }

    def tool_update(self, tool_state: Dict[str, Any]) -> Dict[str, Any]:
        state = dict(tool_state or {})
        tool_id = str(state.get("id") or "")
        start_time = int(state.get("start_time") or 0)
        end_time = state.get("end_time")
        normalized_state: Dict[str, Any] = {
            "status": state.get("status") or "pending",
            "input": state.get("input") if isinstance(state.get("input"), dict) else {},
            "raw": state.get("input_json") or "",
            "output": state.get("output"),
            "error": state.get("error"),
            "title": state.get("title"),
            "metadata": state.get("metadata") if isinstance(state.get("metadata"), dict) else {},
            "attachments": state.get("attachments") if isinstance(state.get("attachments"), list) else [],
            "time": {
                "start": start_time,
                "end": int(end_time) if isinstance(end_time, (int, float)) else None,
            },
        }
        status = str(normalized_state.get("status") or "")
        if status in {"completed", "error"}:
            self._split_text_segment()
        return {
            "id": self._tool_part_id(tool_id or Identifier.ascending("toolpart")),
            "session_id": self._session_id,
            "message_id": self._message_id,
            "type": "tool",
            "tool": state.get("name") or "tool",
            "call_id": tool_id,
            "state": normalized_state,
        }

    def reasoning_start(self, reasoning_id: Optional[str], metadata: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        key = self._reasoning_key(reasoning_id)
        if key in self._reasoning_parts:
            return None
        state = self._new_reasoning_state(key, metadata)
        return {
            "id": state["id"],
            "session_id": self._session_id,
            "message_id": self._message_id,
            "type": "reasoning",
            "text": state["text"],
            "metadata": dict(state["metadata"]),
        }

    def reasoning_delta(
        self,
        reasoning_id: Optional[str],
        delta: str,
        metadata: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        key = self._reasoning_key(reasoning_id)
        state = self._reasoning_parts.get(key)
        if not state:
            state = self._new_reasoning_state(key, metadata)
        if isinstance(metadata, dict) and metadata:
            state["metadata"] = dict(metadata)
        piece = str(delta or "")
        if piece:
            state["text"] = str(state.get("text", "")) + piece
        return {
            "id": state["id"],
            "session_id": self._session_id,
            "message_id": self._message_id,
            "type": "reasoning",
            "text": state["text"],
            "metadata": dict(state.get("metadata") or {}),
        }

    def reasoning_end(self, reasoning_id: Optional[str], metadata: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        key = self._reasoning_key(reasoning_id, create=False)
        if not key:
            return None
        state = self._reasoning_parts.get(key)
        if not state:
            return None
        if isinstance(metadata, dict) and metadata:
            state["metadata"] = dict(metadata)
        part = {
            "id": state["id"],
            "session_id": self._session_id,
            "message_id": self._message_id,
            "type": "reasoning",
            "text": state["text"],
            "metadata": dict(state.get("metadata") or {}),
        }
        del self._reasoning_parts[key]
        if key == self._anonymous_reasoning_key:
            self._anonymous_reasoning_key = None
        return part

    def step_start(self, snapshot: Optional[str]) -> Dict[str, Any]:
        return {
            "id": self._next_part_id(),
            "session_id": self._session_id,
            "message_id": self._message_id,
            "type": "step-start",
            "snapshot": snapshot,
        }

    def step_finish(
        self,
        reason: str,
        snapshot: Optional[str],
        tokens: Optional[Dict[str, Any]] = None,
        cost: float = 0.0,
    ) -> Dict[str, Any]:
        return {
            "id": self._next_part_id(),
            "session_id": self._session_id,
            "message_id": self._message_id,
            "type": "step-finish",
            "reason": str(reason or "completed"),
            "snapshot": snapshot,
            "tokens": dict(tokens or {}),
            "cost": float(cost or 0.0),
        }

    def patch(self, patch_hash: Optional[str], files: Optional[list[str]] = None) -> Dict[str, Any]:
        return {
            "id": self._next_part_id(),
            "session_id": self._session_id,
            "message_id": self._message_id,
            "type": "patch",
            "hash": str(patch_hash or ""),
            "files": list(files or []),
        }
