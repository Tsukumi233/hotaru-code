"""Args context for CLI arguments.

This module provides access to CLI arguments passed to the TUI.
"""

from dataclasses import dataclass
from typing import Optional
from contextvars import ContextVar


@dataclass
class Args:
    """CLI arguments for TUI.

    Attributes:
        model: Model in format provider/model
        agent: Agent name to use
        session_id: Session ID to continue
        continue_session: Whether to continue last session
        prompt: Initial prompt text
    """
    model: Optional[str] = None
    agent: Optional[str] = None
    session_id: Optional[str] = None
    continue_session: bool = False
    prompt: Optional[str] = None


class ArgsContext:
    """Context for accessing CLI arguments."""

    def __init__(self, args: Args) -> None:
        """Initialize with args.

        Args:
            args: CLI arguments
        """
        self._args = args

    @property
    def model(self) -> Optional[str]:
        """Get model argument."""
        return self._args.model

    @property
    def agent(self) -> Optional[str]:
        """Get agent argument."""
        return self._args.agent

    @property
    def session_id(self) -> Optional[str]:
        """Get session ID argument."""
        return self._args.session_id

    @property
    def continue_session(self) -> bool:
        """Get continue session flag."""
        return self._args.continue_session

    @property
    def prompt(self) -> Optional[str]:
        """Get initial prompt."""
        return self._args.prompt


# Context variable
_args_context: ContextVar[Optional[ArgsContext]] = ContextVar(
    "args_context",
    default=None
)


class ArgsProvider:
    """Provider for args context."""

    @classmethod
    def get(cls) -> ArgsContext:
        """Get the current args context."""
        ctx = _args_context.get()
        if ctx is None:
            ctx = ArgsContext(Args())
            _args_context.set(ctx)
        return ctx

    @classmethod
    def provide(cls, args: Args) -> ArgsContext:
        """Create and provide args context.

        Args:
            args: CLI arguments

        Returns:
            The args context
        """
        ctx = ArgsContext(args)
        _args_context.set(ctx)
        return ctx

    @classmethod
    def reset(cls) -> None:
        """Reset the args context."""
        _args_context.set(None)


def use_args() -> ArgsContext:
    """Hook to access args context."""
    return ArgsProvider.get()
