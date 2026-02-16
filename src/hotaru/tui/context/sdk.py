"""SDK context for API communication.

This module provides SDK client context for communicating with
the Hotaru backend API. Uses SessionPrompt for LLM interactions.
"""

from typing import Optional, Dict, Any, Callable, List, AsyncIterator
from contextvars import ContextVar
from pathlib import Path
import asyncio

from ...agent import Agent
from ...core.id import Identifier
from ...project import Project
from ...provider import Provider
from ...session import Session, SessionCompaction, SessionPrompt, SystemPrompt
from ...session.stream_parts import PartStreamBuilder
from ...util.log import Log
from ..message_adapter import structured_messages_to_tui

log = Log.create({"service": "tui.context.sdk"})


class SDKContext:
    """SDK context for API communication.

    Provides methods for interacting with the Hotaru backend API,
    including sending messages, managing sessions, and handling events.
    Uses the real session prompt loop for LLM interactions.
    """

    def __init__(self, cwd: Optional[str] = None) -> None:
        """Initialize SDK context.

        Args:
            cwd: Current working directory (defaults to cwd)
        """
        self._cwd = cwd or str(Path.cwd())
        self._event_handlers: Dict[str, List[Callable[[Dict[str, Any]], None]]] = {}
        self._project: Optional[Any] = None
        self._sandbox: Optional[str] = None

    @property
    def cwd(self) -> str:
        """Get the current working directory."""
        return self._cwd

    async def _ensure_project(self) -> None:
        """Ensure project context is initialized."""
        if self._project is None:
            self._project, self._sandbox = await Project.from_directory(self._cwd)

    async def send_message(
        self,
        session_id: str,
        content: str,
        agent: Optional[str] = None,
        model: Optional[str] = None,
        files: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Send a message and stream the response.

        Uses the real session prompt loop for LLM interactions.

        Args:
            session_id: Session ID
            content: Message content
            agent: Optional agent name
            model: Optional model ID (format: provider/model)
            files: Optional file attachments

        Yields:
            Event dictionaries from the stream
        """
        await self._ensure_project()

        log.info("sending message", {
            "session_id": session_id,
            "content_length": len(content),
            "agent": agent,
            "model": model,
        })

        # Parse model string
        if model:
            provider_id, model_id = Provider.parse_model(model)
        else:
            try:
                provider_id, model_id = await Provider.default_model()
            except RuntimeError as e:
                yield {
                    "type": "error",
                    "data": {"error": str(e)}
                }
                return

        # Validate model exists
        try:
            model_info = await Provider.get_model(provider_id, model_id)
        except Exception as e:
            yield {
                "type": "error",
                "data": {"error": str(e)}
            }
            return

        # Get agent name
        session = await Session.get(session_id)
        agent_name = agent or (session.agent if session else None)
        if agent_name:
            agent_info = await Agent.get(agent_name)
            if not agent_info or agent_info.mode == "subagent":
                agent_name = await Agent.default_agent()
        else:
            agent_name = await Agent.default_agent()

        if session and session.agent != agent_name:
            updated = await Session.update(session_id, agent=agent_name)
            if updated:
                session = updated

        # Build system prompt
        system_prompt = await SystemPrompt.build_full_prompt(
            model=model_info,
            directory=self._cwd,
            worktree=self._sandbox or self._cwd,
            is_git=self._project.vcs == "git" if self._project else False,
        )

        # Track response state
        message_id = Identifier.ascending("message")
        response_text = ""
        part_builder = PartStreamBuilder(session_id=session_id, message_id=message_id)

        # Yield message created event
        yield {
            "type": "message.created",
            "data": {
                "id": message_id,
                "role": "assistant",
                "sessionID": session_id,
            }
        }

        # Callbacks for streaming
        def on_tool_start(tool_name: str, tool_id: str, input_args: Optional[Dict[str, Any]] = None):
            event_queue.put_nowait({
                "kind": "tool_start",
                "tool_name": tool_name,
                "tool_id": tool_id,
                "input": input_args or {},
            })

        def on_tool_end(
            tool_name: str, tool_id: str,
            output: Optional[str], error: Optional[str],
            title: str = "", metadata: Optional[Dict[str, Any]] = None,
        ):
            event_queue.put_nowait({
                "kind": "tool_end",
                "tool_name": tool_name,
                "tool_id": tool_id,
                "output": output,
                "error": error,
                "title": title,
                "metadata": metadata or {},
            })

        def on_tool_update(tool_state: Dict[str, Any]):
            event_queue.put_nowait(
                {
                    "kind": "tool_update",
                    "tool_state": dict(tool_state or {}),
                }
            )

        async def on_reasoning_start(reasoning_id: Optional[str], metadata: Optional[Dict[str, Any]] = None):
            event_queue.put_nowait(
                {
                    "kind": "reasoning_start",
                    "reasoning_id": reasoning_id,
                    "metadata": dict(metadata or {}) if isinstance(metadata, dict) else {},
                }
            )

        async def on_reasoning_delta(
            reasoning_id: Optional[str],
            delta: str,
            metadata: Optional[Dict[str, Any]] = None,
        ):
            event_queue.put_nowait(
                {
                    "kind": "reasoning_delta",
                    "reasoning_id": reasoning_id,
                    "delta": str(delta or ""),
                    "metadata": dict(metadata or {}) if isinstance(metadata, dict) else {},
                }
            )

        async def on_reasoning_end(reasoning_id: Optional[str], metadata: Optional[Dict[str, Any]] = None):
            event_queue.put_nowait(
                {
                    "kind": "reasoning_end",
                    "reasoning_id": reasoning_id,
                    "metadata": dict(metadata or {}) if isinstance(metadata, dict) else {},
                }
            )

        def on_step_start(snapshot: Optional[str]):
            event_queue.put_nowait(
                {
                    "kind": "step_start",
                    "snapshot": snapshot,
                }
            )

        def on_step_finish(
            reason: str,
            snapshot: Optional[str],
            tokens: Optional[Dict[str, Any]] = None,
            cost: float = 0.0,
        ):
            event_queue.put_nowait(
                {
                    "kind": "step_finish",
                    "reason": reason,
                    "snapshot": snapshot,
                    "tokens": dict(tokens or {}),
                    "cost": float(cost or 0.0),
                }
            )

        def on_patch(patch_hash: Optional[str], files: Optional[List[str]] = None):
            event_queue.put_nowait(
                {
                    "kind": "patch",
                    "hash": str(patch_hash or ""),
                    "files": list(files or []),
                }
            )

        # Process with streaming text/tool updates
        # We need to yield events as they come in
        event_queue: asyncio.Queue[Optional[Dict[str, Any]]] = asyncio.Queue()
        result_holder: List[Any] = []
        error_holder: List[str] = []

        async def process_with_queue():
            """Run processor and put events in queue."""
            try:
                def queue_text(text: str):
                    nonlocal response_text
                    response_text += text
                    event_queue.put_nowait({"kind": "text", "text": text})

                prompt_result = await SessionPrompt.prompt(
                    session_id=session_id,
                    content=content,
                    provider_id=provider_id,
                    model_id=model_id,
                    agent=agent_name,
                    cwd=self._cwd,
                    worktree=self._sandbox or self._cwd,
                    system_prompt=system_prompt,
                    on_text=queue_text,
                    on_tool_start=on_tool_start,
                    on_tool_end=on_tool_end,
                    on_tool_update=on_tool_update,
                    on_reasoning_start=on_reasoning_start,
                    on_reasoning_delta=on_reasoning_delta,
                    on_reasoning_end=on_reasoning_end,
                    on_step_start=on_step_start,
                    on_step_finish=on_step_finish,
                    on_patch=on_patch,
                    resume_history=True,
                    assistant_message_id=message_id,
                )
                result_holder.append(prompt_result.result)
            except Exception as e:
                error_holder.append(str(e))
            finally:
                event_queue.put_nowait(None)  # Signal completion

        # Start processing in background
        process_task = asyncio.create_task(process_with_queue())

        def _make_event(evt: Dict[str, Any]):
            """Convert a queue event dict to a yield-able event dict."""
            kind = evt.get("kind")
            if kind == "text":
                part = part_builder.text_delta(str(evt.get("text") or ""))
                if part is None:
                    return None
                return {
                    "type": "message.part.updated",
                    "data": {"part": part},
                }
            elif kind == "tool_start":
                return {
                    "type": "message.part.tool.start",
                    "data": {
                        "tool_name": evt["tool_name"],
                        "tool_id": evt["tool_id"],
                        "input": evt.get("input", {}),
                    }
                }
            elif kind == "tool_end":
                return {
                    "type": "message.part.tool.end",
                    "data": {
                        "tool_name": evt["tool_name"],
                        "tool_id": evt["tool_id"],
                        "output": evt.get("output"),
                        "error": evt.get("error"),
                        "title": evt.get("title", ""),
                        "metadata": evt.get("metadata", {}),
                    }
                }
            elif kind == "tool_update":
                part = part_builder.tool_update(dict(evt.get("tool_state") or {}))
                return {
                    "type": "message.part.updated",
                    "data": {"part": part},
                }
            elif kind == "reasoning_start":
                part = part_builder.reasoning_start(
                    evt.get("reasoning_id"),
                    dict(evt.get("metadata") or {}),
                )
                if part is None:
                    return None
                return {"type": "message.part.updated", "data": {"part": part}}
            elif kind == "reasoning_delta":
                part = part_builder.reasoning_delta(
                    evt.get("reasoning_id"),
                    str(evt.get("delta") or ""),
                    dict(evt.get("metadata") or {}),
                )
                return {
                    "type": "message.part.updated",
                    "data": {"part": part},
                }
            elif kind == "reasoning_end":
                part = part_builder.reasoning_end(
                    evt.get("reasoning_id"),
                    dict(evt.get("metadata") or {}),
                )
                if part is None:
                    return None
                return {"type": "message.part.updated", "data": {"part": part}}
            elif kind == "step_start":
                part = part_builder.step_start(evt.get("snapshot"))
                return {
                    "type": "message.part.updated",
                    "data": {"part": part},
                }
            elif kind == "step_finish":
                part = part_builder.step_finish(
                    reason=str(evt.get("reason") or "completed"),
                    snapshot=evt.get("snapshot"),
                    tokens=dict(evt.get("tokens") or {}),
                    cost=float(evt.get("cost") or 0.0),
                )
                return {
                    "type": "message.part.updated",
                    "data": {"part": part},
                }
            elif kind == "patch":
                part = part_builder.patch(
                    patch_hash=str(evt.get("hash") or ""),
                    files=list(evt.get("files") or []),
                )
                return {
                    "type": "message.part.updated",
                    "data": {"part": part},
                }
            return None

        while True:
            try:
                event = await asyncio.wait_for(event_queue.get(), timeout=0.1)
                if event is None:
                    break
                result_event = _make_event(event)
                if result_event:
                    yield result_event
            except asyncio.TimeoutError:
                # Check if task is done
                if process_task.done():
                    # Drain remaining items
                    while not event_queue.empty():
                        event = event_queue.get_nowait()
                        if event is None:
                            break
                        result_event = _make_event(event)
                        if result_event:
                            yield result_event
                    break

        # Wait for task to complete
        await process_task

        # Check for errors
        if error_holder:
            yield {
                "type": "error",
                "data": {"error": error_holder[0]}
            }
            return

        # Get result
        if result_holder:
            result = result_holder[0]
            if result.error:
                yield {
                    "type": "error",
                    "data": {"error": result.error}
                }
                return

            # Yield completion event
            yield {
                "type": "message.completed",
                "data": {
                    "id": message_id,
                    "finish": "stop",
                    "usage": result.usage,
                }
            }
        else:
            yield {
                "type": "message.completed",
                "data": {
                    "id": message_id,
                    "finish": "stop",
                }
            }

    async def create_session(
        self,
        agent: Optional[str] = None,
        model: Optional[str] = None,
        title: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new session.

        Args:
            agent: Agent name
            model: Model ID (format: provider/model)
            title: Session title

        Returns:
            Session data
        """
        await self._ensure_project()

        # Parse model
        if model:
            provider_id, model_id = Provider.parse_model(model)
        else:
            try:
                provider_id, model_id = await Provider.default_model()
            except RuntimeError:
                provider_id, model_id = "anthropic", "claude-sonnet-4-20250514"

        # Get agent name
        agent_name = agent or await Agent.default_agent()

        # Create session
        session = await Session.create(
            project_id=self._project.id if self._project else "default",
            agent=agent_name,
            directory=self._cwd,
            model_id=model_id,
            provider_id=provider_id,
        )

        log.info("created session", {
            "session_id": session.id,
            "agent": agent_name,
            "model": f"{provider_id}/{model_id}",
        })

        return {
            "id": session.id,
            "title": title or "New Session",
            "agent": agent_name,
            "time": {
                "created": session.time.created,
                "updated": session.time.updated,
            }
        }

    async def compact_session(
        self,
        session_id: str,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run manual session compaction.

        Args:
            session_id: Session to compact
            model: Optional model override (format: provider/model)

        Returns:
            Compact execution result metadata
        """
        await self._ensure_project()

        session = await Session.get(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")

        if model:
            provider_id, model_id = Provider.parse_model(model)
        elif session.provider_id and session.model_id:
            provider_id, model_id = session.provider_id, session.model_id
        else:
            provider_id, model_id = await Provider.default_model()

        model_info = await Provider.get_model(provider_id, model_id)
        agent_name = session.agent or await Agent.default_agent()

        system_prompt = await SystemPrompt.build_full_prompt(
            model=model_info,
            directory=self._cwd,
            worktree=self._sandbox or self._cwd,
            is_git=self._project.vcs == "git" if self._project else False,
        )

        compaction_user_id = await SessionCompaction.create(
            session_id=session_id,
            agent=agent_name,
            provider_id=provider_id,
            model_id=model_id,
            auto=False,
        )

        result = await SessionPrompt.loop(
            session_id=session_id,
            provider_id=provider_id,
            model_id=model_id,
            agent=agent_name,
            cwd=self._cwd,
            worktree=self._sandbox or self._cwd,
            system_prompt=system_prompt,
            resume_history=True,
            auto_compaction=False,
        )
        return {
            "user_message_id": compaction_user_id,
            "assistant_message_id": result.assistant_message_id,
            "status": result.result.status,
            "error": result.result.error,
            "text": result.text,
            "usage": result.result.usage,
        }

    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session data.

        Args:
            session_id: Session ID

        Returns:
            Session data or None
        """
        log.debug("getting session", {"session_id": session_id})
        session = await Session.get(session_id)
        if not session:
            return None

        return {
            "id": session.id,
            "title": session.title or "Untitled",
            "agent": session.agent,
            "time": {
                "created": session.time.created,
                "updated": session.time.updated,
            }
        }

    async def list_sessions(self, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all sessions.

        Args:
            project_id: Optional project ID filter

        Returns:
            List of session data
        """
        await self._ensure_project()
        log.debug("listing sessions")

        pid = project_id or (self._project.id if self._project else None)
        if not pid:
            return []

        sessions = await Session.list(pid)
        return [
            {
                "id": s.id,
                "title": s.title or "Untitled",
                "agent": s.agent,
                "time": {
                    "created": s.time.created,
                    "updated": s.time.updated,
                }
            }
            for s in sessions
        ]

    async def delete_session(self, session_id: str) -> None:
        """Delete a session.

        Args:
            session_id: Session ID
        """
        from ...session import Session
        log.info("deleting session", {"session_id": session_id})
        await Session.delete(session_id)

    async def get_messages(self, session_id: str) -> List[Dict[str, Any]]:
        """Get messages for a session.

        Args:
            session_id: Session ID

        Returns:
            List of messages
        """
        log.debug("getting messages", {"session_id": session_id})
        structured = await Session.messages(session_id=session_id)
        return structured_messages_to_tui(structured)

    async def abort_message(self, session_id: str) -> None:
        """Abort the current message generation.

        Args:
            session_id: Session ID
        """
        # TODO: Implement actual API call
        log.info("aborting message", {"session_id": session_id})

    async def list_providers(self) -> List[Dict[str, Any]]:
        """List available providers.

        Returns:
            List of provider data
        """
        log.debug("listing providers")
        providers = await Provider.list()
        return [
            {
                "id": p.id,
                "name": p.name,
                "models": {
                    model_id: {
                        "id": model_id,
                        "name": model.name,
                        "api_id": model.api_id,
                        "limit": {
                            "context": int(getattr(model.limit, "context", 0) or 0),
                            "output": int(getattr(model.limit, "output", 0) or 0),
                        },
                    }
                    for model_id, model in p.models.items()
                }
            }
            for p in providers
        ]

    async def list_agents(self) -> List[Dict[str, Any]]:
        """List available agents.

        Returns:
            List of agent data
        """
        log.debug("listing agents")
        agents = await Agent.list()
        return [
            {
                "name": a.name,
                "mode": a.mode,
                "description": a.description or "",
            }
            for a in agents
        ]

    def on_event(self, event_type: str, handler: Callable[[Dict[str, Any]], None]) -> Callable[[], None]:
        """Register an event handler.

        Args:
            event_type: Event type to listen for
            handler: Handler function

        Returns:
            Unsubscribe function
        """
        if event_type not in self._event_handlers:
            self._event_handlers[event_type] = []
        self._event_handlers[event_type].append(handler)

        def unsubscribe():
            if event_type in self._event_handlers and handler in self._event_handlers[event_type]:
                self._event_handlers[event_type].remove(handler)

        return unsubscribe

    def emit_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Emit an event to all registered handlers.

        Args:
            event_type: Event type
            data: Event data
        """
        if event_type in self._event_handlers:
            for handler in self._event_handlers[event_type]:
                try:
                    handler(data)
                except Exception as e:
                    log.error("event handler error", {
                        "event_type": event_type,
                        "error": str(e)
                    })


# Context variable
_sdk_context: ContextVar[Optional[SDKContext]] = ContextVar(
    "sdk_context",
    default=None
)


class SDKProvider:
    """Provider for SDK context."""

    _instance: Optional[SDKContext] = None

    @classmethod
    def get(cls) -> SDKContext:
        """Get the current SDK context."""
        ctx = _sdk_context.get()
        if ctx is None:
            ctx = SDKContext()
            _sdk_context.set(ctx)
            cls._instance = ctx
        return ctx

    @classmethod
    def provide(cls, cwd: Optional[str] = None) -> SDKContext:
        """Create and provide SDK context.

        Args:
            cwd: Current working directory

        Returns:
            The SDK context
        """
        ctx = SDKContext(cwd)
        _sdk_context.set(ctx)
        cls._instance = ctx
        return ctx

    @classmethod
    def reset(cls) -> None:
        """Reset the SDK context."""
        _sdk_context.set(None)
        cls._instance = None


def use_sdk() -> SDKContext:
    """Hook to access SDK context."""
    return SDKProvider.get()
