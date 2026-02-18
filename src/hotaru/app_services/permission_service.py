"""Permission application service."""

from __future__ import annotations

from typing import Any

from ..permission import Permission, PermissionReply


class PermissionService:
    """Thin orchestration for permission workflows."""

    @classmethod
    async def list(cls) -> list[dict[str, Any]]:
        pending = await Permission.list_pending()
        return [item.model_dump() for item in pending]

    @classmethod
    async def reply(cls, request_id: str, payload: dict[str, Any]) -> bool:
        reply_value = payload.get("reply")
        if reply_value not in {item.value for item in PermissionReply}:
            raise ValueError("Field 'reply' must be one of: once, always, reject")

        message = payload.get("message")
        await Permission.reply(
            request_id=request_id,
            reply=PermissionReply(str(reply_value)),
            message=message if isinstance(message, str) else None,
        )
        return True
