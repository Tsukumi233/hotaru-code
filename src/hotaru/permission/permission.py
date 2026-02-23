"""Permission system for tool execution.

Controls what actions AI agents can perform based on configurable rules.
"""

import asyncio
import fnmatch
from dataclasses import dataclass
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

    @dataclass
    class _Pending:
        request: PermissionRequest
        session_id: str
        project_id: Optional[str]
        scope: str
        permission: str
        always: List[str]
        future: asyncio.Future[None]

    def __init__(self) -> None:
        self._pending: Dict[str, Permission._Pending] = {}
        self._pending_guard = asyncio.Lock()
        self._approved_session: Dict[str, List[PermissionRule]] = {}
        self._approved_project: Dict[str, List[PermissionRule]] = {}
        self._persisted_loaded: set[str] = set()

    async def _resolve_scope(self) -> str:
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

    async def _resolve_project_id(self, session_id: str) -> Optional[str]:
        try:
            from ..session.session import Session

            session = await Session.get(session_id)
            if session:
                return session.project_id
        except Exception as e:
            log.debug("failed to resolve project id for permission scope", {"session_id": session_id, "error": str(e)})
        return None

    async def _ensure_persisted_loaded(self, project_id: Optional[str]) -> None:
        if not project_id or project_id in self._persisted_loaded:
            return
        self._persisted_loaded.add(project_id)
        from ..storage import NotFoundError, Storage

        try:
            data = await Storage.read(["permission_approval", project_id])
        except NotFoundError:
            self._approved_project[project_id] = []
            return
        except Exception as e:
            log.warn("failed to load persisted permission approvals", {"project_id": project_id, "error": str(e)})
            self._approved_project[project_id] = []
            return

        if isinstance(data, list):
            try:
                self._approved_project[project_id] = self.from_config_list(data)
                return
            except Exception as e:
                log.warn("invalid persisted permission approvals", {"project_id": project_id, "error": str(e)})
        self._approved_project[project_id] = []

    async def _persist_project_approvals(self, project_id: Optional[str]) -> None:
        if not project_id:
            return
        try:
            from ..storage import Storage

            rules = self._approved_project.get(project_id, [])
            await Storage.write(
                ["permission_approval", project_id],
                [rule.model_dump() for rule in rules],
            )
        except Exception as e:
            log.warn("failed to persist permission approvals", {"project_id": project_id, "error": str(e)})

    def _approved_rules(
        self,
        *,
        scope: str,
        session_id: str,
        project_id: Optional[str],
    ) -> List[PermissionRule]:
        if scope == "session":
            return self._approved_session.get(session_id, [])
        if scope in {"project", "persisted"} and project_id:
            return self._approved_project.get(project_id, [])
        return []

    async def _remember_approvals(
        self,
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
            store = self._approved_session.setdefault(session_id, [])
        elif scope in {"project", "persisted"} and project_id:
            store = self._approved_project.setdefault(project_id, [])
        else:
            return

        store.extend(
            PermissionRule(permission=permission, pattern=pattern, action=PermissionAction.ALLOW)
            for pattern in patterns
        )

        if scope == "persisted":
            await self._persist_project_approvals(project_id)

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

    async def ask(
        self,
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
        scope = await self._resolve_scope()
        project_id: Optional[str] = None
        if scope in {"project", "persisted"}:
            project_id = await self._resolve_project_id(session_id)
            if scope == "persisted":
                await self._ensure_persisted_loaded(project_id)
        approved = self._approved_rules(scope=scope, session_id=session_id, project_id=project_id)

        for pattern in patterns:
            rule = self.evaluate(permission, pattern, ruleset, approved)

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
                loop = asyncio.get_running_loop()
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

                item = Permission._Pending(
                    request=request,
                    session_id=session_id,
                    project_id=project_id,
                    scope=scope,
                    permission=permission,
                    always=always or [],
                    future=future,
                )
                async with self._pending_guard:
                    self._pending[rid] = item

                await Bus.publish(PermissionAsked, request)
                await future  # Block until user responds
                return  # After first "ask" pattern resolves, all are approved

            # action == "allow" - continue to next pattern

    @staticmethod
    def _resolve_pending(pending: _Pending) -> None:
        if not pending.future.done():
            pending.future.set_result(None)

    @staticmethod
    def _reject_pending(pending: _Pending, error: Exception) -> None:
        if not pending.future.done():
            pending.future.set_exception(error)

    async def reply(
        self,
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
        async with self._pending_guard:
            pending = self._pending.pop(request_id, None)
        if not pending:
            return

        session_id = pending.session_id

        await Bus.publish(PermissionReplied, PermissionRepliedProperties(
            session_id=session_id,
            request_id=request_id,
            reply=reply
        ))

        if reply == PermissionReply.REJECT:
            # Reject this request
            if message:
                self._reject_pending(pending, CorrectedError(message))
            else:
                self._reject_pending(pending, RejectedError())

            # Also reject ALL other pending requests for this session
            async with self._pending_guard:
                session_pending = [
                    (rid, self._pending.pop(rid))
                    for rid, p in list(self._pending.items())
                    if p.session_id == session_id
                ]
            for rid, p in session_pending:
                await Bus.publish(PermissionReplied, PermissionRepliedProperties(
                    session_id=session_id,
                    request_id=rid,
                    reply=PermissionReply.REJECT,
                ))
                self._reject_pending(p, RejectedError())
            return

        if reply == PermissionReply.ONCE:
            self._resolve_pending(pending)
            return

        if reply == PermissionReply.ALWAYS:
            await self._remember_approvals(
                scope=str(pending.scope or "session"),
                session_id=session_id,
                project_id=pending.project_id,
                permission=pending.permission,
                patterns=list(pending.always),
            )

            self._resolve_pending(pending)

            # Auto-resolve any other pending requests that now match
            auto_pending: List[tuple[str, Permission._Pending]] = []
            async with self._pending_guard:
                for rid, p in list(self._pending.items()):
                    if p.session_id != session_id:
                        continue
                    approved = self._approved_rules(
                        scope=str(p.scope or "session"),
                        session_id=session_id,
                        project_id=p.project_id,
                    )
                    all_approved = True
                    for pat in p.request.patterns:
                        rule = self.evaluate(p.permission, pat, [], approved)
                        if rule.action != PermissionAction.ALLOW:
                            all_approved = False
                            break
                    if not all_approved:
                        continue
                    auto_pending.append((rid, self._pending.pop(rid)))
            for rid, p in auto_pending:
                await Bus.publish(PermissionReplied, PermissionRepliedProperties(
                    session_id=session_id,
                    request_id=rid,
                    reply=PermissionReply.ALWAYS,
                ))
                self._resolve_pending(p)

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

    async def list_pending(self) -> List[PermissionRequest]:
        """List pending permission requests.

        Returns:
            List of pending requests
        """
        async with self._pending_guard:
            return [p.request for p in self._pending.values()]

    async def clear_session(self, session_id: str) -> None:
        async with self._pending_guard:
            request_ids = [rid for rid, item in self._pending.items() if item.session_id == session_id]
            pending = [self._pending.pop(rid) for rid in request_ids]
        self._approved_session.pop(session_id, None)
        for p in pending:
            self._reject_pending(p, RejectedError())

    async def shutdown(self) -> None:
        async with self._pending_guard:
            pending = list(self._pending.values())
            self._pending.clear()
        for item in pending:
            self._reject_pending(item, RejectedError())
        self._approved_session.clear()
        self._approved_project.clear()
        self._persisted_loaded.clear()
