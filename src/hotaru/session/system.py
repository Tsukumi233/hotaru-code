"""System prompt management.

Provides system prompts for different AI providers and models.
"""

import platform
from datetime import date
from pathlib import Path
from typing import List, Optional

from ..provider.provider import ProcessedModelInfo
from ..util.log import Log
from .instruction import InstructionPrompt

log = Log.create({"service": "session.system"})

# Load default prompt
_PROMPT_DIR = Path(__file__).parent / "prompt"
_DEFAULT_PROMPT = (_PROMPT_DIR / "default.txt").read_text(encoding="utf-8")


class SystemPrompt:
    """System prompt generator.

    Generates appropriate system prompts based on the model and environment.
    """

    @classmethod
    def get_default(cls) -> str:
        """Get the default system prompt."""
        return _DEFAULT_PROMPT

    @classmethod
    def for_model(cls, model: ProcessedModelInfo) -> List[str]:
        """Get system prompts for a specific model.

        Args:
            model: Model information

        Returns:
            List of system prompt strings
        """
        # For now, use the same prompt for all models
        # In the future, we can customize based on model capabilities
        return [_DEFAULT_PROMPT]

    @classmethod
    def environment(
        cls,
        model: ProcessedModelInfo,
        directory: Optional[str] = None,
        is_git: bool = False,
    ) -> str:
        """Generate environment information for the system prompt.

        Args:
            model: Model information
            directory: Working directory (defaults to Instance.directory())
            is_git: Whether the directory is a git repository

        Returns:
            Environment information string
        """
        cwd = directory or "."
        today = date.today().isoformat()
        os_platform = platform.system().lower()

        lines = [
            f"You are powered by the model named {model.name}. The exact model ID is {model.provider_id}/{model.api_id}.",
            "",
            "Here is useful information about the environment you are running in:",
            "<env>",
            f"Working directory: {cwd}",
            f"Is directory a git repo: {'Yes' if is_git else 'No'}",
            f"Platform: {os_platform}",
            f"Today's date: {today}",
            "</env>",
        ]

        return "\n".join(lines)

    @classmethod
    async def build_full_prompt(
        cls,
        model: ProcessedModelInfo,
        directory: Optional[str] = None,
        worktree: Optional[str] = None,
        is_git: bool = False,
        additional_instructions: Optional[List[str]] = None,
    ) -> str:
        """Build a complete system prompt.

        Args:
            model: Model information
            directory: Working directory
            worktree: Project boundary/worktree root
            is_git: Whether the directory is a git repository
            additional_instructions: Additional instructions to append

        Returns:
            Complete system prompt string
        """
        parts = []

        # Add base prompt
        parts.extend(cls.for_model(model))

        # Add environment info
        parts.append(cls.environment(model, directory, is_git))

        # Load project/global custom instructions (AGENTS.md, config.instructions, etc.)
        try:
            parts.extend(await InstructionPrompt.system(directory=directory, worktree=worktree))
        except Exception as e:
            log.warn("failed to load instruction prompts", {"error": str(e)})

        # Add additional instructions
        if additional_instructions:
            parts.extend(additional_instructions)

        return "\n\n".join(parts)
