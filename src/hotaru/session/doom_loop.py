"""Doom loop detection for repeated tool calls."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from ..permission import Permission


class DoomLoopDetector:
    """Detect repeated identical tool calls and trigger permission prompt."""

    def __init__(
        self,
        *,
        permission: Permission,
        session_id: str,
        threshold: int = 3,
        window: int = 50,
        signatures: Optional[List[str]] = None,
    ) -> None:
        self.permission = permission
        self.session_id = session_id
        self.threshold = threshold
        self.window = window
        self.signatures = signatures if signatures is not None else []

    async def check(
        self,
        *,
        tool_name: str,
        tool_input: Dict[str, Any],
        ruleset: List[Dict[str, Any]],
    ) -> None:
        signature = f"{tool_name}:{json.dumps(tool_input, sort_keys=True, default=str)}"
        self.signatures.append(signature)
        if len(self.signatures) > self.window:
            self.signatures[:] = self.signatures[-self.window :]

        if len(self.signatures) < self.threshold:
            return

        recent = self.signatures[-self.threshold :]
        if len(set(recent)) != 1:
            return

        from ..permission import Permission

        await self.permission.ask(
            session_id=self.session_id,
            permission="doom_loop",
            patterns=[tool_name],
            ruleset=Permission.from_config_list(ruleset),
            always=[tool_name],
            metadata={
                "tool": tool_name,
                "input": tool_input,
            },
        )
