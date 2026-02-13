"""Session turn helpers for undo/redo behavior."""

from typing import Any, Dict, List, Tuple


def split_messages_for_undo(
    messages: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split session messages into remaining + removed for one undo step.

    A step is defined as everything from the latest user message onward.
    """
    last_user_index = -1
    for index, message in enumerate(messages):
        if message.get("role") == "user":
            last_user_index = index

    if last_user_index < 0:
        return list(messages), []
    return messages[:last_user_index], messages[last_user_index:]


def extract_user_text_from_turn(turn_messages: List[Dict[str, Any]]) -> str:
    """Extract text content from the first user message in a removed turn."""
    for message in turn_messages:
        if message.get("role") != "user":
            continue
        chunks: List[str] = []
        for part in message.get("parts", []):
            if isinstance(part, dict) and part.get("type") == "text":
                text = part.get("text")
                if isinstance(text, str):
                    chunks.append(text)
        return "".join(chunks)
    return ""
