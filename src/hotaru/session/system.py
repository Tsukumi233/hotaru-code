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

_PROMPT_DIR = Path(__file__).parent / "prompt"


def _load_prompt(filename: str, fallback: str) -> str:
    try:
        return (_PROMPT_DIR / filename).read_text(encoding="utf-8").strip()
    except Exception:
        return fallback


_DEFAULT_PROMPT = _load_prompt("default.txt", "You are Hotaru Code, an AI-powered coding assistant.")
_PROMPT_CODEX = _load_prompt("codex_header.txt", _DEFAULT_PROMPT)
_PROMPT_ANTHROPIC = _load_prompt("anthropic.txt", _DEFAULT_PROMPT)
_PROMPT_QWEN = _load_prompt("qwen.txt", _DEFAULT_PROMPT)
_PROMPT_GEMINI = _load_prompt("gemini.txt", _DEFAULT_PROMPT)
_PROMPT_TRINITY = _load_prompt("trinity.txt", _DEFAULT_PROMPT)


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
        model_id = (model.id or "").lower()
        family = (model.family or "").lower()
        name = (model.name or "").lower()
        provider = (model.provider_id or "").lower()
        api_type = str(model.api_type or "").lower()

        if "gpt-5" in model_id or "gpt-5" in name:
            return [_PROMPT_CODEX]

        if "qwen" in model_id or "qwen" in family or "qwen" in name:
            return [_PROMPT_QWEN]

        if "gemini" in model_id or "gemini" in family or "gemini" in name:
            return [_PROMPT_GEMINI]

        if (
            "claude" in model_id
            or "claude" in family
            or "claude" in name
            or provider == "anthropic"
            or api_type == "anthropic"
        ):
            return [_PROMPT_ANTHROPIC]

        if "trinity" in model_id or "trinity" in family or "trinity" in name:
            return [_PROMPT_TRINITY]

        if (
            "gpt-" in model_id
            or "gpt-" in name
            or model_id.startswith("o1")
            or model_id.startswith("o3")
        ):
            return [_PROMPT_CODEX]

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
