"""Permission system for tool execution.

Controls what actions AI agents can perform based on configurable rules.
"""

import asyncio
import fnmatch
import os
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from ..core.bus import Bus, BusEvent
from ..core.id import Identifier
from ..util.log import Log

log = Log.create({"service": "permission"})


class PermissionAction(str, Enum):
    """Permission action types."""
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


class PermissionRule(BaseModel):
    """A permission rule."""
    permission: str
    pattern: str
    action: PermissionAction

    class Config:
        use_enum_values = True


class PermissionRequest(BaseModel):
    """A permission request."""
    id: str
    session_id: str
    permission: str
    patterns: List[str]
    metadata: Dict[str, Any] = Field(default_factory=dict)
    always: List[str] = Field(default_factory=list)
    tool: Optional[Dict[str, str]] = None


class PermissionReply(str, Enum):
    """Permission reply types."""
    ONCE = "once"
    ALWAYS = "always"
    REJECT = "reject"


# Permission events
PermissionAsked = BusEvent(
    event_type="permission.asked",
    properties_type=PermissionRequest
)


class PermissionRepliedProperties(BaseModel):
    """Properties for permission replied event."""
    session_id: str
    request_id: str
    reply: PermissionReply


PermissionReplied = BusEvent(
    event_type="permission.replied",
    properties_type=PermissionRepliedProperties
)


class RejectedError(Exception):
    """User rejected permission without a message."""

    def __init__(self):
        super().__init__("The user rejected permission to use this specific tool call.")


class CorrectedError(Exception):
    """User rejected permission with guidance."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(
            f"The user rejected permission to use this specific tool call "
            f"with the following feedback: {message}"
        )


class DeniedError(Exception):
    """Permission denied by configuration rule."""

    def __init__(self, ruleset: List[PermissionRule]):
        self.ruleset = ruleset
        super().__init__(
            f"The user has specified a rule which prevents you from using "
            f"this specific tool call. Relevant rules: {ruleset}"
        )


def _expand_pattern(pattern: str) -> str:
    """Expand home directory patterns."""
    home = str(Path.home())

    if pattern.startswith("~/"):
        return home + pattern[1:]
    if pattern == "~":
        return home
    if pattern.startswith("$HOME/"):
        return home + pattern[5:]
    if pattern.startswith("$HOME"):
        return home + pattern[5:]

    return pattern


def _wildcard_match(value: str, pattern: str) -> bool:
    """Match a value against a wildcard pattern.

    Supports * and ** wildcards.
    """
    if pattern == "*":
        return True

    # Use fnmatch for glob-style matching
    return fnmatch.fnmatch(value, pattern)


class Permission:
    """Permission management.

    Evaluates and manages permission rules for tool execution.
    """

    # Pending permission requests
    _pending: Dict[str, Dict[str, Any]] = {}

    # Approved rules per project
    _approved: Dict[str, List[PermissionRule]] = {}

    @classmethod
    def from_config(cls, config: Dict[str, Any] | str) -> List[PermissionRule]:
        """Convert config permission dict to ruleset.

        Args:
            config: Permission configuration

        Returns:
            List of permission rules
        """
        ruleset: List[PermissionRule] = []

        if isinstance(config, str):
            return [
                PermissionRule(
                    permission="*",
                    action=PermissionAction(config),
                    pattern="*",
                )
            ]

        for key, value in config.items():
            if isinstance(value, str):
                ruleset.append(PermissionRule(
                    permission=key,
                    action=PermissionAction(value),
                    pattern="*"
                ))
            elif isinstance(value, dict):
                for pattern, action in value.items():
                    ruleset.append(PermissionRule(
                        permission=key,
                        pattern=_expand_pattern(pattern),
                        action=PermissionAction(action)
                    ))

        return ruleset

    @classmethod
    def merge(cls, *rulesets: List[PermissionRule]) -> List[PermissionRule]:
        """Merge multiple rulesets.

        Args:
            rulesets: Rulesets to merge

        Returns:
            Merged ruleset (later rules take precedence)
        """
        result = []
        for ruleset in rulesets:
            result.extend(ruleset)
        return result

    @classmethod
    def evaluate(
        cls,
        permission: str,
        pattern: str,
        *rulesets: List[PermissionRule]
    ) -> PermissionRule:
        """Evaluate permission against rulesets.

        Args:
            permission: Permission type (e.g., "edit", "bash")
            pattern: Pattern to check (e.g., file path, command)
            rulesets: Rulesets to check

        Returns:
            Matching rule (last match wins) or default ask rule
        """
        merged = cls.merge(*rulesets)

        log.info("evaluating permission", {
            "permission": permission,
            "pattern": pattern,
            "rule_count": len(merged)
        })

        # Find last matching rule
        match = None
        for rule in merged:
            if _wildcard_match(permission, rule.permission) and _wildcard_match(pattern, rule.pattern):
                match = rule

        if match:
            return match

        # Default to ask
        return PermissionRule(
            permission=permission,
            pattern="*",
            action=PermissionAction.ASK
        )

    @classmethod
    def from_config_list(cls, rules: List[Dict[str, Any]]) -> List[PermissionRule]:
        """Convert a list of permission config dicts to PermissionRule objects.

        Args:
            rules: List of dicts with permission, pattern, action keys

        Returns:
            List of PermissionRule objects
        """
        return [
            PermissionRule(
                permission=r["permission"],
                pattern=_expand_pattern(r.get("pattern", "*")),
                action=PermissionAction(r["action"]),
            )
            for r in rules
        ]

    @classmethod
    async def ask(
        cls,
        session_id: str,
        permission: str,
        patterns: List[str],
        ruleset: List[PermissionRule],
        always: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None
    ) -> None:
        """Request permission for an action.

        Evaluates the permission against the ruleset. If the action is "allow",
        returns immediately. If "deny", raises DeniedError. If "ask", publishes
        a PermissionAsked event and blocks on an asyncio.Future until the user
        responds via reply().

        Args:
            session_id: Session ID
            permission: Permission type
            patterns: Patterns to request permission for
            ruleset: Current ruleset
            always: Patterns to remember if approved
            metadata: Additional metadata
            request_id: Optional request ID

        Raises:
            DeniedError: If permission is denied by rule
            RejectedError: If user rejects
            CorrectedError: If user rejects with feedback
        """
        approved = cls._approved.get(session_id, [])

        for pattern in patterns:
            rule = cls.evaluate(permission, pattern, ruleset, approved)

            log.info("evaluated", {
                "permission": permission,
                "pattern": pattern,
                "action": rule.action
            })

            if rule.action == PermissionAction.DENY:
                matching_rules = [
                    r for r in ruleset
                    if _wildcard_match(permission, r.permission)
                ]
                raise DeniedError(matching_rules)

            if rule.action == PermissionAction.ASK:
                rid = request_id or Identifier.ascending("permission")
                loop = asyncio.get_event_loop()
                future = loop.create_future()

                request = PermissionRequest(
                    id=rid,
                    session_id=session_id,
                    permission=permission,
                    patterns=patterns,
                    metadata=metadata or {},
                    always=always or [],
                )

                cls._pending[rid] = {
                    "request": request,
                    "session_id": session_id,
                    "permission": permission,
                    "always": always or [],
                    "resolve": lambda f=future: f.set_result(None) if not f.done() else None,
                    "reject": lambda e, f=future: f.set_exception(e) if not f.done() else None,
                }

                await Bus.publish(PermissionAsked, request)
                await future  # Block until user responds
                return  # After first "ask" pattern resolves, all are approved

            # action == "allow" - continue to next pattern

    @classmethod
    async def reply(
        cls,
        request_id: str,
        reply: PermissionReply,
        message: Optional[str] = None
    ) -> None:
        """Reply to a permission request.

        On reject: rejects ALL pending requests for the same session.
        On always: adds to approved rules, then auto-resolves any other
        pending requests that now match.

        Args:
            request_id: Request ID
            reply: Reply type
            message: Optional message for rejection
        """
        pending = cls._pending.get(request_id)
        if not pending:
            return

        del cls._pending[request_id]

        session_id = pending["session_id"]

        await Bus.publish(PermissionReplied, PermissionRepliedProperties(
            session_id=session_id,
            request_id=request_id,
            reply=reply
        ))

        if reply == PermissionReply.REJECT:
            # Reject this request
            if message:
                pending["reject"](CorrectedError(message))
            else:
                pending["reject"](RejectedError())

            # Also reject ALL other pending requests for this session
            session_pending = [
                (rid, p) for rid, p in list(cls._pending.items())
                if p["session_id"] == session_id
            ]
            for rid, p in session_pending:
                del cls._pending[rid]
                p["reject"](RejectedError())
            return

        if reply == PermissionReply.ONCE:
            pending["resolve"]()
            return

        if reply == PermissionReply.ALWAYS:
            # Add to approved rules
            if session_id not in cls._approved:
                cls._approved[session_id] = []

            for pattern in pending.get("always", []):
                cls._approved[session_id].append(PermissionRule(
                    permission=pending["permission"],
                    pattern=pattern,
                    action=PermissionAction.ALLOW
                ))

            pending["resolve"]()

            # Auto-resolve any other pending requests that now match
            approved = cls._approved.get(session_id, [])
            auto_resolved = []
            for rid, p in list(cls._pending.items()):
                if p["session_id"] != session_id:
                    continue
                # Check if all patterns are now approved
                all_approved = True
                for pat in p["request"].patterns:
                    rule = cls.evaluate(p["permission"], pat, [], approved)
                    if rule.action != PermissionAction.ALLOW:
                        all_approved = False
                        break
                if all_approved:
                    auto_resolved.append(rid)

            for rid in auto_resolved:
                p = cls._pending.pop(rid)
                p["resolve"]()

    @classmethod
    def disabled_tools(
        cls,
        tools: List[str],
        ruleset: List[PermissionRule]
    ) -> set:
        """Get tools that are disabled by rules.

        Args:
            tools: List of tool names
            ruleset: Current ruleset

        Returns:
            Set of disabled tool names
        """
        edit_tools = {"edit", "write", "patch", "apply_patch", "multiedit"}
        result = set()

        for tool in tools:
            # Map edit-related tools to "edit" permission
            permission = "edit" if tool in edit_tools else tool

            # Find matching rule
            for rule in reversed(ruleset):
                if _wildcard_match(permission, rule.permission):
                    if rule.pattern == "*" and rule.action == PermissionAction.DENY:
                        result.add(tool)
                    break

        return result

    @classmethod
    async def list_pending(cls) -> List[PermissionRequest]:
        """List pending permission requests.

        Returns:
            List of pending requests
        """
        return [p["request"] for p in cls._pending.values()]

    @classmethod
    def reset(cls) -> None:
        """Reset permission state."""
        cls._pending.clear()
        cls._approved.clear()
