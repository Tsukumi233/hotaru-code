"""Message rendering helpers for the session screen."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from ..context import use_local


def render_part(
    part: Dict[str, Any],
    *,
    show_thinking: bool,
    show_tool_details: bool,
) -> str:
    """Render a message part to display text."""
    part_type = str(part.get("type") or "")
    if part_type == "text":
        return str(part.get("text") or "")
    if part_type == "reasoning":
        if not show_thinking:
            return ""
        text = str(part.get("text") or "").strip()
        if not text:
            return ""
        return f"_Thinking:_\n\n{text}"
    if part_type == "step-start":
        return "_Step started._"
    if part_type == "step-finish":
        reason = str(part.get("reason") or "completed")
        lines = [f"_Step finished: {reason}._"]
        if show_tool_details:
            tokens = part.get("tokens")
            if isinstance(tokens, dict):
                token_line = (
                    f"input={int(tokens.get('input', 0) or 0)}, "
                    f"output={int(tokens.get('output', 0) or 0)}, "
                    f"reasoning={int(tokens.get('reasoning', 0) or 0)}"
                )
                lines.extend(["", f"`{token_line}`"])
        return "\n".join(lines)
    if part_type == "patch":
        files = part.get("files")
        file_list = files if isinstance(files, list) else []
        lines = [f"_Patch changed {len(file_list)} file(s)._"]
        if show_tool_details and file_list:
            lines.append("")
            lines.extend(f"- `{str(item)}`" for item in file_list)
        return "\n".join(lines)
    if part_type == "compaction":
        mode = "auto" if bool(part.get("auto")) else "manual"
        return f"_Compaction checkpoint ({mode})._"
    if part_type == "subtask":
        description = str(part.get("description") or "subtask")
        agent = str(part.get("agent") or "subagent")
        return f"**Subtask ({agent}):** {description}"
    if part_type == "file":
        filename = str(part.get("filename") or "attachment")
        url = str(part.get("url") or "")
        if url:
            return f"**File:** {filename} ({url})"
        return f"**File:** {filename}"
    return ""


def assistant_label(info: Any, *, show_metadata: bool) -> Optional[str]:
    """Build the assistant label from message info."""
    if not show_metadata:
        return None
    agent = use_local().agent.current().get("name", "assistant")
    if not isinstance(info, dict):
        return agent
    info_agent = info.get("agent")
    if isinstance(info_agent, str) and info_agent:
        agent = info_agent
    model = info.get("model")
    if isinstance(model, dict):
        provider_id = str(model.get("provider_id") or "")
        model_id = str(model.get("model_id") or "")
        if provider_id and model_id:
            return f"{agent} · {provider_id}/{model_id}"
        if model_id:
            return f"{agent} · {model_id}"
    return agent


def message_timestamp(info: Any, *, show: bool) -> Optional[str]:
    """Format a message timestamp from info dict."""
    if not show or not isinstance(info, dict):
        return None
    time_data = info.get("time")
    if not isinstance(time_data, dict):
        return None
    created = time_data.get("created")
    if not isinstance(created, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(created / 1000).astimezone().strftime("%H:%M:%S")
    except (ValueError, OSError):
        return None


def now_timestamp(*, show: bool) -> Optional[str]:
    """Return current time as HH:MM:SS if timestamps are enabled."""
    if not show:
        return None
    return datetime.now().astimezone().strftime("%H:%M:%S")


def extract_text(message: Dict[str, Any]) -> str:
    """Extract user-visible text from a message's parts."""
    parts = message.get("parts", [])
    chunks: List[str] = []
    files: List[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        part_type = part.get("type")
        if part_type == "text":
            text = part.get("text")
            if isinstance(text, str):
                chunks.append(text)
        if part_type == "file":
            files.append(str(part.get("filename") or "attachment"))
    base = "".join(chunks)
    if not files:
        return base
    attached = ", ".join(files[:3])
    if len(files) > 3:
        attached = f"{attached}, ..."
    suffix = f"[Attached: {attached}]"
    return f"{base}\n\n{suffix}" if base else suffix


def stringify_output(output: Any) -> str:
    """Coerce output to string."""
    if output is None:
        return ""
    if isinstance(output, str):
        return output
    return str(output)


def should_hide_tool(part: Dict[str, Any], *, show_details: bool) -> bool:
    """Determine if a tool part should be hidden."""
    if show_details:
        return False
    state = part.get("state")
    if not isinstance(state, dict):
        return False
    status = state.get("status")
    error = state.get("error")
    return status == "completed" and not error
