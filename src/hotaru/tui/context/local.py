"""Local context for agent and model selection.

This module provides local state management for the currently
selected agent and model in the TUI.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any, Callable, Tuple
from contextvars import ContextVar
import json
from pathlib import Path

from ...core.global_paths import GlobalPath
from ...util.log import Log

log = Log.create({"service": "tui.context.local"})


@dataclass
class ModelSelection:
    """Model selection state.

    Attributes:
        provider_id: Provider identifier
        model_id: Model identifier
    """
    provider_id: str
    model_id: str


class AgentState:
    """State management for agent selection."""

    def __init__(self, agents: List[Dict[str, Any]]) -> None:
        """Initialize agent state.

        Args:
            agents: List of available agents
        """
        self._agents = agents
        self._current = agents[0]["name"] if agents else "build"
        self._listeners: List[Callable[[str], None]] = []

    def list(self) -> List[Dict[str, Any]]:
        """Get list of available agents."""
        return [a for a in self._agents if a.get("mode") != "subagent" and not a.get("hidden")]

    def current(self) -> Dict[str, Any]:
        """Get current agent info."""
        for agent in self._agents:
            if agent["name"] == self._current:
                return agent
        return self._agents[0] if self._agents else {"name": "build"}

    def set(self, name: str) -> bool:
        """Set current agent by name.

        Args:
            name: Agent name

        Returns:
            True if agent was found and set
        """
        for agent in self._agents:
            if agent["name"] == name:
                self._current = name
                self._notify()
                return True
        return False

    def move(self, direction: int) -> None:
        """Move to next/previous agent.

        Args:
            direction: 1 for next, -1 for previous
        """
        agents = self.list()
        if not agents:
            return

        current_idx = 0
        for i, agent in enumerate(agents):
            if agent["name"] == self._current:
                current_idx = i
                break

        next_idx = (current_idx + direction) % len(agents)
        self._current = agents[next_idx]["name"]
        self._notify()

    def _notify(self) -> None:
        """Notify listeners of change."""
        for listener in self._listeners:
            try:
                listener(self._current)
            except Exception as e:
                log.error("agent listener error", {"error": str(e)})

    def on_change(self, callback: Callable[[str], None]) -> Callable[[], None]:
        """Register change listener."""
        self._listeners.append(callback)
        return lambda: self._listeners.remove(callback) if callback in self._listeners else None


class ModelState:
    """State management for model selection."""

    def __init__(self, providers: List[Dict[str, Any]]) -> None:
        """Initialize model state.

        Args:
            providers: List of available providers
        """
        self._providers = providers
        self._current: Optional[ModelSelection] = None
        self._recent: List[ModelSelection] = []
        self._favorite: List[ModelSelection] = []
        self._per_agent: Dict[str, ModelSelection] = {}
        self._listeners: List[Callable[[Optional[ModelSelection]], None]] = []
        self._path = Path(GlobalPath.state()) / "model.json"
        self._load()
        self._ensure_current()

    def _is_available(self, model: ModelSelection) -> bool:
        for provider in self._providers:
            if provider.get("id") != model.provider_id:
                continue
            models = provider.get("models", {})
            return model.model_id in models
        return False

    def _ensure_current(self) -> None:
        if self._current and self._is_available(self._current):
            return

        self._current = None
        for model in self._recent:
            if self._is_available(model):
                self._current = model
                return

    def _load(self) -> None:
        """Load model state from disk."""
        try:
            if self._path.exists():
                with open(self._path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "recent" in data:
                        self._recent = [
                            ModelSelection(m["provider_id"], m["model_id"])
                            for m in data["recent"]
                            if "provider_id" in m and "model_id" in m
                        ]
                    if "favorite" in data:
                        self._favorite = [
                            ModelSelection(m["provider_id"], m["model_id"])
                            for m in data["favorite"]
                            if "provider_id" in m and "model_id" in m
                        ]
                    current = data.get("current")
                    if (
                        isinstance(current, dict)
                        and "provider_id" in current
                        and "model_id" in current
                    ):
                        self._current = ModelSelection(
                            current["provider_id"],
                            current["model_id"],
                        )
        except Exception as e:
            log.warning("failed to load model state", {"error": str(e)})

    def _save(self) -> None:
        """Save model state to disk."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump({
                    "current": (
                        {
                            "provider_id": self._current.provider_id,
                            "model_id": self._current.model_id,
                        }
                        if self._current
                        else None
                    ),
                    "recent": [
                        {"provider_id": m.provider_id, "model_id": m.model_id}
                        for m in self._recent
                    ],
                    "favorite": [
                        {"provider_id": m.provider_id, "model_id": m.model_id}
                        for m in self._favorite
                    ],
                }, f, indent=2)
        except Exception as e:
            log.warning("failed to save model state", {"error": str(e)})

    def current(self) -> Optional[ModelSelection]:
        """Get current model selection."""
        return self._current

    def recent(self) -> List[ModelSelection]:
        """Get recent model selections."""
        return self._recent.copy()

    def favorite(self) -> List[ModelSelection]:
        """Get favorite models."""
        return self._favorite.copy()

    def set(
        self,
        model: ModelSelection,
        agent_name: Optional[str] = None,
        add_to_recent: bool = True
    ) -> None:
        """Set current model.

        Args:
            model: Model selection
            agent_name: Optional agent to associate with
            add_to_recent: Whether to add to recent list
        """
        self._current = model
        if agent_name:
            self._per_agent[agent_name] = model

        if add_to_recent:
            # Remove if already in recent
            self._recent = [
                m for m in self._recent
                if not (m.provider_id == model.provider_id and m.model_id == model.model_id)
            ]
            # Add to front
            self._recent.insert(0, model)
            # Limit to 10
            self._recent = self._recent[:10]
        self._save()

        self._notify()

    def cycle(self, direction: int) -> None:
        """Cycle through recent models.

        Args:
            direction: 1 for next, -1 for previous
        """
        if not self._recent:
            return

        current = self._current
        if not current:
            self._current = self._recent[0]
            self._notify()
            return

        # Find current in recent
        current_idx = -1
        for i, m in enumerate(self._recent):
            if m.provider_id == current.provider_id and m.model_id == current.model_id:
                current_idx = i
                break

        if current_idx == -1:
            self._current = self._recent[0]
        else:
            next_idx = (current_idx + direction) % len(self._recent)
            self._current = self._recent[next_idx]

        self._save()
        self._notify()

    def toggle_favorite(self, model: ModelSelection) -> bool:
        """Toggle model as favorite.

        Args:
            model: Model to toggle

        Returns:
            True if now a favorite, False if removed
        """
        for i, m in enumerate(self._favorite):
            if m.provider_id == model.provider_id and m.model_id == model.model_id:
                self._favorite.pop(i)
                self._save()
                return False

        self._favorite.insert(0, model)
        self._save()
        return True

    def is_favorite(self, model: ModelSelection) -> bool:
        """Check if model is a favorite."""
        for m in self._favorite:
            if m.provider_id == model.provider_id and m.model_id == model.model_id:
                return True
        return False

    def first_available(self) -> Optional[ModelSelection]:
        """Return first available provider/model pair."""
        for provider in self._providers:
            provider_id = provider.get("id")
            models = provider.get("models", {})
            if not provider_id or not models:
                continue
            first_model_id = next(iter(models.keys()), None)
            if not first_model_id:
                continue
            return ModelSelection(provider_id=provider_id, model_id=first_model_id)
        return None

    def is_available(self, model: ModelSelection) -> bool:
        """Check whether a model exists in current provider list."""
        return self._is_available(model)

    def _notify(self) -> None:
        """Notify listeners of change."""
        for listener in self._listeners:
            try:
                listener(self._current)
            except Exception as e:
                log.error("model listener error", {"error": str(e)})

    def on_change(
        self,
        callback: Callable[[Optional[ModelSelection]], None]
    ) -> Callable[[], None]:
        """Register change listener."""
        self._listeners.append(callback)
        return lambda: self._listeners.remove(callback) if callback in self._listeners else None


class LocalContext:
    """Local context for agent and model state."""

    def __init__(
        self,
        agents: Optional[List[Dict[str, Any]]] = None,
        providers: Optional[List[Dict[str, Any]]] = None
    ) -> None:
        """Initialize local context.

        Args:
            agents: Available agents
            providers: Available providers
        """
        self.agent = AgentState(agents or [{"name": "build"}])
        self.model = ModelState(providers or [])

    def update_agents(self, agents: List[Dict[str, Any]]) -> None:
        """Update available agents."""
        self.agent = AgentState(agents)

    def update_providers(self, providers: List[Dict[str, Any]]) -> None:
        """Update available providers."""
        self.model = ModelState(providers)


# Context variable
_local_context: ContextVar[Optional[LocalContext]] = ContextVar(
    "local_context",
    default=None
)


class LocalProvider:
    """Provider for local context."""

    _instance: Optional[LocalContext] = None

    @classmethod
    def get(cls) -> LocalContext:
        """Get the current local context."""
        ctx = _local_context.get()
        if ctx is None:
            ctx = LocalContext()
            _local_context.set(ctx)
            cls._instance = ctx
        return ctx

    @classmethod
    def provide(
        cls,
        agents: Optional[List[Dict[str, Any]]] = None,
        providers: Optional[List[Dict[str, Any]]] = None
    ) -> LocalContext:
        """Create and provide local context.

        Args:
            agents: Available agents
            providers: Available providers

        Returns:
            The local context
        """
        ctx = LocalContext(agents, providers)
        _local_context.set(ctx)
        cls._instance = ctx
        return ctx

    @classmethod
    def reset(cls) -> None:
        """Reset the local context."""
        _local_context.set(None)
        cls._instance = None


def use_local() -> LocalContext:
    """Hook to access local context."""
    return LocalProvider.get()
