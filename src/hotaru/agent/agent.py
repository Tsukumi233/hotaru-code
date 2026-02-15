"""Agent definitions and management.

Agents are configured AI personas with specific permissions and behaviors.
"""

from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from ..core.config import ConfigManager
from ..core.global_paths import GlobalPath
from ..util.log import Log

log = Log.create({"service": "agent"})


class AgentMode(str, Enum):
    """Agent mode types."""
    SUBAGENT = "subagent"
    PRIMARY = "primary"
    ALL = "all"


class AgentModel(BaseModel):
    """Model configuration for an agent."""
    provider_id: str
    model_id: str


class AgentInfo(BaseModel):
    """Agent configuration."""
    name: str
    description: Optional[str] = None
    mode: AgentMode = AgentMode.ALL
    native: bool = False
    hidden: bool = False
    top_p: Optional[float] = None
    temperature: Optional[float] = None
    color: Optional[str] = None
    permission: List[Dict[str, Any]] = Field(default_factory=list)
    model: Optional[AgentModel] = None
    variant: Optional[str] = None
    prompt: Optional[str] = None
    options: Dict[str, Any] = Field(default_factory=dict)
    steps: Optional[int] = None

    model_config = ConfigDict(use_enum_values=True)


_PROMPT_DIR = Path(__file__).parent / "prompt"


def _read_prompt(filename: str, fallback: str) -> str:
    try:
        return (_PROMPT_DIR / filename).read_text(encoding="utf-8").strip()
    except Exception:
        return fallback


PROMPT_EXPLORE = _read_prompt(
    "explore.txt",
    "You are a file search specialist. Use Glob, Grep, and Read to explore codebases quickly and accurately.",
)
PROMPT_TITLE = _read_prompt(
    "title.txt",
    "Generate a concise title for this conversation. Output only the title.",
)
PROMPT_SUMMARY = _read_prompt(
    "summary.txt",
    "Summarize what was done in this conversation in 2-3 concise sentences.",
)
PROMPT_COMPACTION = _read_prompt(
    "compaction.txt",
    "Summarize this conversation for future continuation, preserving key decisions and next steps.",
)


class Agent:
    """Agent registry and management.

    Provides access to configured agents with their permissions and settings.
    """

    _agents: Optional[Dict[str, AgentInfo]] = None

    @classmethod
    async def _initialize(cls) -> Dict[str, AgentInfo]:
        """Initialize agents from configuration."""
        if cls._agents is not None:
            return cls._agents

        log.info("initializing agents")
        config = await ConfigManager.get()

        def parse_permissions(permission_config: Optional[Dict[str, Any] | str]) -> List[Dict[str, Any]]:
            rules: List[Dict[str, Any]] = []
            if not permission_config:
                return rules

            def expand_pattern(pattern: str) -> str:
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

            if isinstance(permission_config, str):
                return [{"permission": "*", "pattern": "*", "action": permission_config}]

            for key, value in permission_config.items():
                if isinstance(value, str):
                    rules.append({
                        "permission": key,
                        "pattern": "*",
                        "action": value,
                    })
                    continue

                if isinstance(value, dict):
                    for pattern, action in value.items():
                        rules.append({
                            "permission": key,
                            "pattern": expand_pattern(pattern),
                            "action": action,
                        })

            return rules

        def parse_tools(tools_config: Optional[Dict[str, bool]]) -> List[Dict[str, Any]]:
            if not tools_config:
                return []
            rules: List[Dict[str, Any]] = []
            for tool_name, enabled in tools_config.items():
                action = "allow" if enabled else "deny"
                permission_name = (
                    "edit"
                    if tool_name in {"write", "edit", "patch", "apply_patch", "multiedit"}
                    else tool_name
                )
                rules.append({
                    "permission": permission_name,
                    "pattern": "*",
                    "action": action,
                })
            return rules

        tool_output_glob = str(Path(GlobalPath.data()) / "tool-output" / "*")
        strict_permissions = bool(config.strict_permissions)
        try:
            from ..skill.skill import Skill

            skill_globs = [str(Path(directory) / "*") for directory in await Skill.directories()]
        except Exception:
            skill_globs = []

        # Default permission rules
        global_plan_glob = str(Path(GlobalPath.data()) / "plans" / "*")
        local_plan_glob = "*/.hotaru/plans/*"
        default_permissions = [
            {"permission": "*", "pattern": "*", "action": "allow"},
            {"permission": "doom_loop", "pattern": "*", "action": "ask"},
            {"permission": "external_directory", "pattern": "*", "action": "ask"},
            {"permission": "external_directory", "pattern": tool_output_glob, "action": "allow"},
            {"permission": "read", "pattern": "*.env", "action": "ask"},
            {"permission": "read", "pattern": "*.env.*", "action": "ask"},
            {"permission": "read", "pattern": "*.env.example", "action": "allow"},
            {"permission": "question", "pattern": "*", "action": "deny"},
            {"permission": "plan_enter", "pattern": "*", "action": "deny"},
            {"permission": "plan_exit", "pattern": "*", "action": "deny"},
        ]
        for glob in skill_globs:
            default_permissions.append({"permission": "external_directory", "pattern": glob, "action": "allow"})
        if strict_permissions:
            default_permissions.extend([
                {"permission": "edit", "pattern": "*", "action": "ask"},
                {"permission": "bash", "pattern": "*", "action": "ask"},
            ])

        # User permissions from config
        user_permissions = parse_permissions(config.permission)

        def merge_permissions(*rulesets):
            """Merge permission rulesets."""
            result = []
            for ruleset in rulesets:
                result.extend(ruleset)
            return result

        # Built-in agents
        agents: Dict[str, AgentInfo] = {
            "build": AgentInfo(
                name="build",
                description="The default agent. Executes tools based on configured permissions.",
                mode=AgentMode.PRIMARY,
                native=True,
                permission=merge_permissions(
                    default_permissions,
                    [
                        {"permission": "question", "pattern": "*", "action": "allow"},
                        {"permission": "plan_enter", "pattern": "*", "action": "allow"},
                    ],
                    user_permissions
                ),
            ),
            "plan": AgentInfo(
                name="plan",
                description="Plan mode. Disallows all edit tools except the plan file.",
                mode=AgentMode.PRIMARY,
                native=True,
                permission=merge_permissions(
                    default_permissions,
                    [
                        {"permission": "question", "pattern": "*", "action": "allow"},
                        {"permission": "plan_exit", "pattern": "*", "action": "allow"},
                        {"permission": "external_directory", "pattern": global_plan_glob, "action": "allow"},
                        {"permission": "edit", "pattern": "*", "action": "deny"},
                        {"permission": "edit", "pattern": local_plan_glob, "action": "allow"},
                        {"permission": "edit", "pattern": global_plan_glob, "action": "allow"},
                    ],
                    user_permissions
                ),
            ),
            "general": AgentInfo(
                name="general",
                description="General-purpose agent for researching complex questions and executing multi-step tasks.",
                mode=AgentMode.SUBAGENT,
                native=True,
                permission=merge_permissions(
                    default_permissions,
                    [
                        {"permission": "todowrite", "pattern": "*", "action": "deny"},
                        {"permission": "todoread", "pattern": "*", "action": "deny"},
                    ],
                    user_permissions,
                ),
            ),
            "explore": AgentInfo(
                name="explore",
                description=(
                    "Fast agent specialized for exploring codebases. Use this when you need to "
                    "quickly find files by patterns, search code for keywords, or answer questions "
                    "about the codebase."
                ),
                mode=AgentMode.SUBAGENT,
                native=True,
                prompt=PROMPT_EXPLORE,
                permission=merge_permissions(
                    [
                        {"permission": "*", "pattern": "*", "action": "deny"},
                        {"permission": "grep", "pattern": "*", "action": "allow"},
                        {"permission": "glob", "pattern": "*", "action": "allow"},
                        {"permission": "list", "pattern": "*", "action": "allow"},
                        {"permission": "read", "pattern": "*", "action": "allow"},
                        {"permission": "bash", "pattern": "*", "action": "ask" if strict_permissions else "allow"},
                    ],
                    user_permissions
                ),
            ),
            "compaction": AgentInfo(
                name="compaction",
                mode=AgentMode.PRIMARY,
                native=True,
                hidden=True,
                prompt=PROMPT_COMPACTION,
                permission=[{"permission": "*", "pattern": "*", "action": "deny"}],
            ),
            "title": AgentInfo(
                name="title",
                mode=AgentMode.PRIMARY,
                native=True,
                hidden=True,
                temperature=0.5,
                prompt=PROMPT_TITLE,
                permission=[{"permission": "*", "pattern": "*", "action": "deny"}],
            ),
            "summary": AgentInfo(
                name="summary",
                mode=AgentMode.PRIMARY,
                native=True,
                hidden=True,
                prompt=PROMPT_SUMMARY,
                permission=[{"permission": "*", "pattern": "*", "action": "deny"}],
            ),
        }

        # Apply config overrides
        if config.agent:
            for name, agent_config in config.agent.items():
                if agent_config.disable:
                    if name in agents:
                        del agents[name]
                    continue

                if name not in agents:
                    agents[name] = AgentInfo(
                        name=name,
                        mode=AgentMode.ALL,
                        permission=merge_permissions(default_permissions, user_permissions),
                    )

                agent = agents[name]

                if agent_config.model:
                    parts = agent_config.model.split("/", 1)
                    if len(parts) == 2:
                        agent.model = AgentModel(
                            provider_id=parts[0],
                            model_id=parts[1]
                        )

                if agent_config.variant:
                    agent.variant = agent_config.variant
                if agent_config.prompt:
                    agent.prompt = agent_config.prompt
                if agent_config.description:
                    agent.description = agent_config.description
                if agent_config.name:
                    agent.name = agent_config.name
                if agent_config.temperature is not None:
                    agent.temperature = agent_config.temperature
                if agent_config.top_p is not None:
                    agent.top_p = agent_config.top_p
                if agent_config.mode:
                    agent.mode = AgentMode(agent_config.mode)
                if agent_config.color:
                    agent.color = agent_config.color
                if agent_config.hidden is not None:
                    agent.hidden = agent_config.hidden
                if agent_config.effective_steps is not None:
                    agent.steps = agent_config.effective_steps
                if agent_config.options:
                    agent.options.update(agent_config.options)
                if agent_config.model_extra:
                    extra_options = {
                        key: value for key, value in agent_config.model_extra.items()
                        if key not in {
                            "name",
                            "model",
                            "variant",
                            "temperature",
                            "top_p",
                            "prompt",
                            "disable",
                            "description",
                            "mode",
                            "hidden",
                            "steps",
                            "maxSteps",
                            "max_steps",
                            "color",
                            "tools",
                            "permission",
                            "options",
                        }
                    }
                    if extra_options:
                        agent.options.update(extra_options)
                if agent_config.tools:
                    agent.permission = merge_permissions(
                        agent.permission,
                        parse_tools(agent_config.tools),
                    )
                if agent_config.permission:
                    agent.permission = merge_permissions(
                        agent.permission,
                        parse_permissions(agent_config.permission),
                    )

        cls._agents = agents
        return agents

    @classmethod
    async def get(cls, name: str) -> Optional[AgentInfo]:
        """Get an agent by name.

        Args:
            name: Agent name

        Returns:
            AgentInfo or None
        """
        agents = await cls._initialize()
        return agents.get(name)

    @classmethod
    async def list(cls) -> List[AgentInfo]:
        """List all agents.

        Returns:
            List of agents, sorted with default agent first
        """
        config = await ConfigManager.get()
        agents = await cls._initialize()

        default_name = config.default_agent or "build"

        # Sort with default agent first
        return sorted(
            agents.values(),
            key=lambda a: (a.name != default_name, a.name)
        )

    @classmethod
    async def default_agent(cls) -> str:
        """Get the default agent name.

        Returns:
            Name of the default agent
        """
        config = await ConfigManager.get()
        agents = await cls._initialize()

        if config.default_agent:
            agent = agents.get(config.default_agent)
            if not agent:
                raise ValueError(f"Default agent '{config.default_agent}' not found")
            if agent.mode == AgentMode.SUBAGENT:
                raise ValueError(f"Default agent '{config.default_agent}' is a subagent")
            if agent.hidden:
                raise ValueError(f"Default agent '{config.default_agent}' is hidden")
            return agent.name

        # Find first primary visible agent
        for agent in agents.values():
            if agent.mode != AgentMode.SUBAGENT and not agent.hidden:
                return agent.name

        raise ValueError("No primary visible agent found")

    @classmethod
    def reset(cls) -> None:
        """Reset the agent cache."""
        cls._agents = None
