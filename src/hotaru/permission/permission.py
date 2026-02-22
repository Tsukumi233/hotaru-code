"""Permission system for tool execution.

Controls what actions AI agents can perform based on configurable rules.
"""

import asyncio
import fnmatch
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from ..core.bus import Bus, BusEvent
from ..core.id import Identifier
from .constants import permission_for_tool
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

    model_config = ConfigDict(use_enum_values=True)


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
    _pending_guard = asyncio.Lock()

    # Approved rules per scope
    _approved_session: Dict[str, List[PermissionRule]] = {}
    _approved_project: Dict[str, List[PermissionRule]] = {}
    _persisted_loaded: set[str] = set()

    @classmethod
    async def _resolve_scope(cls) -> str:
        scope = "session"
        try:
            from ..core.config import ConfigManager

            config = await ConfigManager.get()
            configured = config.permission_memory_scope
            if configured:
                candidate = str(configured)
                if candidate in {"turn", "session", "project", "persisted"}:
                    scope = candidate
        except Exception as e:
            log.debug("failed to resolve permission memory scope", {"error": str(e)})
        return scope

    @classmethod
    async def _resolve_project_id(cls, session_id: str) -> Optional[str]:
        try:
            from ..session.session import Session

            session = await Session.get(session_id)
            if session:
                return session.project_id
        except Exception as e:
            log.debug("failed to resolve project id for permission scope", {"session_id": session_id, "error": str(e)})
        return None

    @classmethod
    async def _ensure_persisted_loaded(cls, project_id: Optional[str]) -> None:
        if not project_id or project_id in cls._persisted_loaded:
            return
        cls._persisted_loaded.add(project_id)
        from ..storage import NotFoundError, Storage

        try:
            data = await Storage.read(["permission_approval", project_id])
        except NotFoundError:
            cls._approved_project[project_id] = []
            return
        except Exception as e:
            log.warn("failed to load persisted permission approvals", {"project_id": project_id, "error": str(e)})
            cls._approved_project[project_id] = []
            return

        if isinstance(data, list):
            try:
                cls._approved_project[project_id] = cls.from_config_list(data)
                return
            except Exception as e:
                log.warn("invalid persisted permission approvals", {"project_id": project_id, "error": str(e)})
        cls._approved_project[project_id] = []

    @classmethod
    async def _persist_project_approvals(cls, project_id: Optional[str]) -> None:
        if not project_id:
            return
        try:
            from ..storage import Storage

            rules = cls._approved_project.get(project_id, [])
            await Storage.write(
                ["permission_approval", project_id],
                [rule.model_dump() for rule in rules],
            )
        except Exception as e:
            log.warn("failed to persist permission approvals", {"project_id": project_id, "error": str(e)})

    @classmethod
    def _approved_rules(
        cls,
        *,
        scope: str,
        session_id: str,
        project_id: Optional[str],
    ) -> List[PermissionRule]:
        if scope == "session":
            return cls._approved_session.get(session_id, [])
        if scope in {"project", "persisted"} and project_id:
            return cls._approved_project.get(project_id, [])
        return []

    @classmethod
    async def _remember_approvals(
        cls,
        *,
        scope: str,
        session_id: str,
        project_id: Optional[str],
        permission: str,
        patterns: List[str],
    ) -> None:
        if scope == "turn":
            return
        if scope == "session":
            store = cls._approved_session.setdefault(session_id, [])
        elif scope in {"project", "persisted"} and project_id:
            store = cls._approved_project.setdefault(project_id, [])
        else:
            return

        store.extend(
            PermissionRule(permission=permission, pattern=pattern, action=PermissionAction.ALLOW)
            for pattern in patterns
        )

        if scope == "persisted":
            await cls._persist_project_approvals(project_id)

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
        request_id: Optional[str] = None,
        tool: Optional[Dict[str, str]] = None,
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
            tool: Optional tool reference with message_id/call_id

        Raises:
            DeniedError: If permission is denied by rule
            RejectedError: If user rejects
            CorrectedError: If user rejects with feedback
        """
        scope = await cls._resolve_scope()
        project_id: Optional[str] = None
        if scope in {"project", "persisted"}:
            project_id = await cls._resolve_project_id(session_id)
            if scope == "persisted":
                await cls._ensure_persisted_loaded(project_id)
        approved = cls._approved_rules(scope=scope, session_id=session_id, project_id=project_id)

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
                    tool=tool,
                )

                item = {
                    "request": request,
                    "session_id": session_id,
                    "project_id": project_id,
                    "scope": scope,
                    "permission": permission,
                    "always": always or [],
                    "resolve": lambda f=future: f.set_result(None) if not f.done() else None,
                    "reject": lambda e, f=future: f.set_exception(e) if not f.done() else None,
                }
                async with cls._pending_guard:
                    cls._pending[rid] = item

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
        async with cls._pending_guard:
            pending = cls._pending.pop(request_id, None)
        if not pending:
            return

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
            async with cls._pending_guard:
                session_pending = [
                    (rid, cls._pending.pop(rid))
                    for rid, p in list(cls._pending.items())
                    if p["session_id"] == session_id
                ]
            for rid, p in session_pending:
                await Bus.publish(PermissionReplied, PermissionRepliedProperties(
                    session_id=session_id,
                    request_id=rid,
                    reply=PermissionReply.REJECT,
                ))
                p["reject"](RejectedError())
            return

        if reply == PermissionReply.ONCE:
            pending["resolve"]()
            return

        if reply == PermissionReply.ALWAYS:
            await cls._remember_approvals(
                scope=str(pending.get("scope") or "session"),
                session_id=session_id,
                project_id=pending.get("project_id"),
                permission=pending["permission"],
                patterns=list(pending.get("always", [])),
            )

            pending["resolve"]()

            # Auto-resolve any other pending requests that now match
            auto_pending = []
            async with cls._pending_guard:
                for rid, p in list(cls._pending.items()):
                    if p["session_id"] != session_id:
                        continue
                    approved = cls._approved_rules(
                        scope=str(p.get("scope") or "session"),
                        session_id=session_id,
                        project_id=p.get("project_id"),
                    )
                    all_approved = True
                    for pat in p["request"].patterns:
                        rule = cls.evaluate(p["permission"], pat, [], approved)
                        if rule.action != PermissionAction.ALLOW:
                            all_approved = False
                            break
                    if not all_approved:
                        continue
                    auto_pending.append((rid, cls._pending.pop(rid)))
            for rid, p in auto_pending:
                await Bus.publish(PermissionReplied, PermissionRepliedProperties(
                    session_id=session_id,
                    request_id=rid,
                    reply=PermissionReply.ALWAYS,
                ))
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
        result = set()

        for tool in tools:
            permission = permission_for_tool(tool)

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
        async with cls._pending_guard:
            return [p["request"] for p in cls._pending.values()]

    @classmethod
    def reset(cls) -> None:
        """Reset permission state."""
        cls._pending.clear()
        cls._pending_guard = asyncio.Lock()
        cls._approved_session.clear()
        cls._approved_project.clear()
        cls._persisted_loaded.clear()
