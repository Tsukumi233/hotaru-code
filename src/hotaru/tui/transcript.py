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
    role = str(message.get("role") or "")
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

    metadata = message.get("metadata", {})
    assistant = metadata.get("assistant", {}) if isinstance(metadata, dict) else {}
    provider_id = assistant.get("provider_id") if isinstance(assistant, dict) else None
    model_id = assistant.get("model_id") if isinstance(assistant, dict) else None

    model_label = "assistant"
    if provider_id and model_id:
        model_label = f"{provider_id}/{model_id}"
    elif model_id:
        model_label = str(model_id)

    duration = _format_duration(metadata)
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

    if part_type == "tool-invocation":
        invocation = part.get("tool_invocation")
        if not isinstance(invocation, dict):
            return []
        return _format_tool_invocation(invocation, options)

    if part_type == "file":
        filename = part.get("filename") or "attachment"
        url = part.get("url") or ""
        return [f"**File:** {filename} ({url})", ""]

    if part_type == "source-url":
        title = part.get("title") or part.get("url") or "source"
        url = part.get("url") or ""
        return [f"**Source:** {title} ({url})", ""]

    return []


def _format_tool_invocation(invocation: Dict[str, Any], options: TranscriptOptions) -> List[str]:
    tool_name = invocation.get("tool_name") or "tool"
    state = invocation.get("state") or "call"
    lines = [f"**Tool: {tool_name}**"]

    if options.tool_details:
        args = invocation.get("args")
        if args not in (None, "", {}):
            lines.extend(["", "**Input:**", "```json", _to_json(args), "```"])

        if state == "result":
            result = invocation.get("result")
            if result not in (None, ""):
                lines.extend(["", "**Output:**", "```", str(result), "```"])

    lines.append("")
    return lines


def _to_json(value: Any) -> str:
    try:
        return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(value)


def _format_duration(metadata: Any) -> str:
    if not isinstance(metadata, dict):
        return ""
    time_data = metadata.get("time")
    if not isinstance(time_data, dict):
        return ""
    created = time_data.get("created")
    completed = time_data.get("completed")
    if not isinstance(created, (int, float)) or not isinstance(completed, (int, float)):
        return ""
    if completed < created:
        return ""
    return f"{(completed - created) / 1000:.1f}s"


def _format_timestamp(timestamp: Any) -> str:
    if not isinstance(timestamp, (int, float)):
        return "unknown"
    try:
        return datetime.fromtimestamp(timestamp / 1000).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    except (ValueError, OSError):
        return "unknown"
