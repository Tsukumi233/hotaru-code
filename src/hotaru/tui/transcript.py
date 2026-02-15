"""Transcript formatting utilities for TUI session export flows."""

from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any, Dict, Iterable, List, Optional


@dataclass(frozen=True)
class TranscriptOptions:
    """Options that control transcript rendering."""

    thinking: bool = False
    tool_details: bool = True
    assistant_metadata: bool = True


def format_transcript(
    session: Dict[str, Any],
    messages: Iterable[Dict[str, Any]],
    options: Optional[TranscriptOptions] = None,
) -> str:
    """Render a session transcript as markdown."""
    opts = options or TranscriptOptions()
    title = str(session.get("title") or "Untitled")
    session_id = str(session.get("id") or "")
    created = _format_timestamp(session.get("time", {}).get("created"))
    updated = _format_timestamp(session.get("time", {}).get("updated"))

    lines: List[str] = [
        f"# {title}",
        "",
        f"**Session ID:** {session_id}",
        f"**Created:** {created}",
        f"**Updated:** {updated}",
        "",
        "---",
        "",
    ]

    for message in messages:
        lines.extend(_format_message(message, opts))
        lines.extend(["---", ""])

    return "\n".join(lines).rstrip() + "\n"


def _format_message(message: Dict[str, Any], options: TranscriptOptions) -> List[str]:
    role = _message_role(message)
    parts = message.get("parts", [])

    lines: List[str] = []
    if role == "user":
        lines.extend(["## User", ""])
    else:
        lines.extend(_format_assistant_header(message, options))

    if isinstance(parts, list):
        for part in parts:
            if not isinstance(part, dict):
                continue
            lines.extend(_format_part(part, options))

    if not lines or lines[-1] != "":
        lines.append("")
    return lines


def _format_assistant_header(message: Dict[str, Any], options: TranscriptOptions) -> List[str]:
    if not options.assistant_metadata:
        return ["## Assistant", ""]

    provider_id, model_id = _assistant_model(message)

    model_label = "assistant"
    if provider_id and model_id:
        model_label = f"{provider_id}/{model_id}"
    elif model_id:
        model_label = str(model_id)

    duration = _format_duration(message)
    if duration:
        return [f"## Assistant ({model_label} · {duration})", ""]
    return [f"## Assistant ({model_label})", ""]


def _format_part(part: Dict[str, Any], options: TranscriptOptions) -> List[str]:
    part_type = part.get("type")
    if part_type == "text":
        text = str(part.get("text") or "")
        if not text.strip():
            return []
        return [text, ""]

    if part_type == "reasoning":
        if not options.thinking:
            return []
        text = str(part.get("text") or "")
        if not text.strip():
            return []
        return ["_Thinking:_", "", text, ""]

    if part_type == "tool":
        return _format_tool_part(part, options)

    if part_type == "step-start":
        return ["_Step started._", ""]

    if part_type == "step-finish":
        reason = str(part.get("reason") or "completed")
        lines = [f"_Step finished: {reason}._"]
        if options.tool_details:
            tokens = part.get("tokens")
            if isinstance(tokens, dict):
                token_line = (
                    f"input={int(tokens.get('input', 0) or 0)}, "
                    f"output={int(tokens.get('output', 0) or 0)}, "
                    f"reasoning={int(tokens.get('reasoning', 0) or 0)}"
                )
                lines.extend(["", f"`{token_line}`"])
        lines.append("")
        return lines

    if part_type == "compaction":
        auto = bool(part.get("auto"))
        mode = "auto" if auto else "manual"
        return [f"_Compaction checkpoint ({mode})._", ""]

    if part_type == "subtask":
        description = str(part.get("description") or "subtask")
        agent = str(part.get("agent") or "subagent")
        return [f"**Subtask ({agent}):** {description}", ""]

    if part_type == "file":
        filename = part.get("filename") or "attachment"
        url = part.get("url") or ""
        return [f"**File:** {filename} ({url})", ""]

    return []


def _format_tool_part(part: Dict[str, Any], options: TranscriptOptions) -> List[str]:
    tool_name = part.get("tool") or "tool"
    state = part.get("state")
    if not isinstance(state, dict):
        return [f"**Tool: {tool_name}**", ""]

    status = str(state.get("status") or "unknown")
    lines = [f"**Tool: {tool_name} ({status})**"]

    if options.tool_details:
        input_data = state.get("input")
        if input_data not in (None, "", {}):
            lines.extend(["", "**Input:**", "```json", _to_json(input_data), "```"])

        if status == "completed":
            output = state.get("output")
            if output not in (None, ""):
                lines.extend(["", "**Output:**", "```", str(output), "```"])
        elif status == "error":
            error = state.get("error")
            if error not in (None, ""):
                lines.extend(["", "**Error:**", "```", str(error), "```"])

    lines.append("")
    return lines


def _to_json(value: Any) -> str:
    try:
        return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(value)


def _format_duration(message: Dict[str, Any]) -> str:
    info = message.get("info")
    if not isinstance(info, dict):
        return ""
    time_data = info.get("time")
    if not isinstance(time_data, dict):
        return ""
    created = time_data.get("created")
    completed = time_data.get("completed")
    if not isinstance(created, (int, float)) or not isinstance(completed, (int, float)):
        return ""
    if completed < created:
        return ""
    return f"{(completed - created) / 1000:.1f}s"


def _assistant_model(message: Dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    info = message.get("info")
    if isinstance(info, dict):
        model = info.get("model")
        if isinstance(model, dict):
            provider_id = model.get("provider_id")
            model_id = model.get("model_id")
            return (
                str(provider_id) if provider_id else None,
                str(model_id) if model_id else None,
            )
    return None, None


def _message_role(message: Dict[str, Any]) -> str:
    role = message.get("role")
    if role:
        return str(role)
    info = message.get("info")
    if isinstance(info, dict) and info.get("role"):
        return str(info.get("role"))
    return ""


def _format_timestamp(timestamp: Any) -> str:
    if not isinstance(timestamp, (int, float)):
        return "unknown"
    try:
        return datetime.fromtimestamp(timestamp / 1000).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    except (ValueError, OSError):
        return "unknown"
