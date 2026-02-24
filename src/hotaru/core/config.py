"""Configuration management.

Loads and merges configuration from multiple sources with proper precedence.
"""

import json
import os
import re
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .global_paths import GlobalPath
from .config_markdown import parse_markdown_config
from ..permission.constants import permission_for_tool
from ..util.log import Log

log = Log.create({"service": "config"})


class PermissionAction(str, Enum):
    """Permission action types."""
    ASK = "ask"
    ALLOW = "allow"
    DENY = "deny"


class PermissionMemoryScope(str, Enum):
    """Scope used for remember/always permission approvals."""

    TURN = "turn"
    SESSION = "session"
    PROJECT = "project"
    PERSISTED = "persisted"


class McpLocalConfig(BaseModel):
    """Local MCP server configuration."""
    type: Literal["local"]
    command: List[str]
    environment: Optional[Dict[str, str]] = None
    enabled: Optional[bool] = None
    timeout: Optional[int] = None


class McpRemoteConfig(BaseModel):
    """Remote MCP server configuration."""
    type: Literal["remote"]
    url: str
    enabled: Optional[bool] = None
    headers: Optional[Dict[str, str]] = None
    timeout: Optional[int] = None
    oauth: Optional[Union[bool, Dict[str, Any]]] = None


McpConfig = Union[McpLocalConfig, McpRemoteConfig]


class AgentConfig(BaseModel):
    """Agent configuration."""
    name: Optional[str] = None
    model: Optional[str] = None
    variant: Optional[str] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    prompt: Optional[str] = None
    disable: Optional[bool] = None
    description: Optional[str] = None
    mode: Optional[Literal["subagent", "primary", "all"]] = None
    hidden: Optional[bool] = None
    steps: Optional[int] = None
    color: Optional[str] = None
    tools: Optional[Dict[str, bool]] = None
    permission: Optional[Union[str, Dict[str, Any]]] = None
    options: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    @model_validator(mode="before")
    @classmethod
    def _reject_legacy_steps(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        if "maxSteps" in value or "max_steps" in value:
            raise ValueError("Legacy field 'maxSteps' is not supported. Use 'steps' instead.")
        return value


class CommandConfig(BaseModel):
    """Command configuration."""
    template: str
    description: Optional[str] = None
    agent: Optional[str] = None
    model: Optional[str] = None
    subtask: Optional[bool] = None


class CustomModelConfig(BaseModel):
    """Custom model configuration."""
    name: Optional[str] = None
    limit: Optional[Dict[str, int]] = None
    options: Optional[Dict[str, Any]] = None
    headers: Optional[Dict[str, str]] = None

    model_config = ConfigDict(extra="allow")


class ProviderConfig(BaseModel):
    """Provider configuration.

    Supports both overriding existing providers and defining custom providers.

    For custom OpenAI-compatible providers:
        {
            "type": "openai",
            "name": "My Provider",
            "options": {
                "baseURL": "https://api.myprovider.com/v1",
                "apiKey": "optional-key"
            },
            "models": {
                "my-model": {
                    "name": "My Model Display Name"
                }
            }
        }

    Supported types:
        - "openai": OpenAI-compatible API (default)
        - "anthropic": Anthropic-compatible API
    """
    # Provider type: "openai" (default) or "anthropic"
    type: Optional[Literal["openai", "anthropic"]] = None

    # Display name
    name: Optional[str] = None

    # Model configurations
    models: Optional[Dict[str, CustomModelConfig]] = None

    # Provider options (includes baseURL, apiKey, headers)
    options: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="before")
    @classmethod
    def _reject_legacy_model_filters(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        if "whitelist" in value or "blacklist" in value:
            raise ValueError("Legacy fields 'whitelist/blacklist' are not supported.")
        return value


class ServerConfig(BaseModel):
    """Server configuration."""
    port: Optional[int] = None
    hostname: Optional[str] = None
    mdns: Optional[bool] = None
    mdns_domain: Optional[str] = Field(None, alias="mdnsDomain")
    cors: Optional[List[str]] = None


class SkillsConfig(BaseModel):
    """Skills configuration."""
    paths: List[str] = Field(default_factory=list)
    urls: List[str] = Field(default_factory=list)


class CompactionConfig(BaseModel):
    """Compaction settings."""
    auto: Optional[bool] = None
    prune: Optional[bool] = None
    reserved: Optional[int] = None


class TuiConfig(BaseModel):
    """TUI configuration."""
    scroll_speed: Optional[float] = None
    diff_style: Optional[Literal["auto", "stacked"]] = None


class ExperimentalConfig(BaseModel):
    """Experimental feature toggles."""

    batch_tool: bool = False
    plan_mode: bool = False
    enable_exa: bool = False
    lsp_tool: bool = False
    primary_tools: List[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class Config(BaseModel):
    """Main configuration schema."""
    schema_: Optional[str] = Field(None, alias="$schema")
    theme: Optional[str] = None
    log_level: Optional[str] = Field(None, alias="logLevel")

    # Model settings
    model: Optional[str] = None
    small_model: Optional[str] = None
    default_agent: Optional[str] = None
    username: Optional[str] = None

    # Provider settings
    provider: Optional[Dict[str, ProviderConfig]] = None
    disabled_providers: Optional[List[str]] = None
    enabled_providers: Optional[List[str]] = None

    # Agent settings
    agent: Optional[Dict[str, AgentConfig]] = None

    # Command settings
    command: Optional[Dict[str, CommandConfig]] = None

    # Skills settings
    skills: SkillsConfig = Field(default_factory=SkillsConfig)

    # MCP settings
    mcp: Optional[Dict[str, McpConfig]] = None

    # Permission settings
    permission: Optional[Union[str, Dict[str, Any]]] = None
    permission_memory_scope: PermissionMemoryScope = PermissionMemoryScope.SESSION
    tools: Optional[Dict[str, bool]] = None
    strict_permissions: Optional[bool] = None
    continue_loop_on_deny: bool = False
    experimental: ExperimentalConfig = Field(default_factory=ExperimentalConfig)

    # Server settings
    server: Optional[ServerConfig] = None
    tui: Optional[TuiConfig] = None

    # Feature settings
    plugin: Optional[List[str]] = None
    instructions: Optional[List[str]] = None
    snapshot: Optional[bool] = None
    share: Optional[Literal["manual", "auto", "disabled"]] = None
    autoupdate: Optional[Union[bool, Literal["notify"]]] = None
    compaction: Optional[CompactionConfig] = None

    # LSP/Formatter
    lsp: Optional[Union[Literal[False], Dict[str, Any]]] = None
    formatter: Optional[Union[Literal[False], Dict[str, Any]]] = None

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def _get_managed_config_dir() -> str:
    """Get platform-specific managed config directory."""
    import platform
    system = platform.system()

    if system == "Darwin":
        return "/Library/Application Support/hotaru"
    elif system == "Windows":
        program_data = os.environ.get("ProgramData", "C:\\ProgramData")
        return os.path.join(program_data, "hotaru")
    else:
        return "/etc/hotaru"


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Deep merge two dictionaries."""
    result = base.copy()

    for key, value in override.items():
        if (
            key in {"plugin", "instructions"}
            and isinstance(result.get(key), list)
            and isinstance(value, list)
        ):
            merged = []
            for item in [*result[key], *value]:
                if item not in merged:
                    merged.append(item)
            result[key] = merged
        elif key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value

    return result


def _substitute_env_vars(text: str) -> str:
    """Replace {env:VAR} patterns with environment variable values."""
    def replacer(match):
        var_name = match.group(1)
        return os.environ.get(var_name, "")

    return re.sub(r'\{env:([^}]+)\}', replacer, text)


def _load_json_file(filepath: str) -> Dict[str, Any]:
    """Load a JSON or JSONC file."""
    path = Path(filepath)
    if not path.exists():
        return {}

    try:
        text = path.read_text(encoding="utf-8")
        text = _substitute_env_vars(text)

        # Simple JSONC handling: remove single-line comments
        # Only remove comments that are NOT inside strings
        lines = []
        for line in text.split("\n"):
            stripped = line.strip()
            # Skip full-line comments
            if stripped.startswith("//"):
                continue

            # For inline comments, we need to be careful not to remove // inside strings
            # Simple approach: only remove // if it's not preceded by : and a quote
            # This handles URLs like "https://..." correctly
            if "//" in line:
                # Check if // appears outside of a string
                in_string = False
                result_chars = []
                i = 0
                while i < len(line):
                    char = line[i]
                    if char == '"' and (i == 0 or line[i-1] != '\\'):
                        in_string = not in_string
                    if not in_string and line[i:i+2] == '//':
                        # Found comment outside string, stop here
                        break
                    result_chars.append(char)
                    i += 1
                line = ''.join(result_chars)

            lines.append(line)
        text = "\n".join(lines)

        return json.loads(text)
    except Exception as e:
        log.error("failed to load config file", {"path": filepath, "error": str(e)})
        return {}


def _relative_without_ext(path: Path, base: Path) -> str:
    """Get forward-slash relative path without suffix."""
    rel = path.relative_to(base)
    return rel.with_suffix("").as_posix()


def _load_agent_markdown_dir(root: str) -> Dict[str, Any]:
    """Load agent markdown files from ``agent/`` and ``agents/`` under root."""
    result: Dict[str, Any] = {}
    root_path = Path(root)

    for subdir in ("agent", "agents"):
        base = root_path / subdir
        if not base.is_dir():
            continue

        for file in sorted(base.rglob("*.md")):
            try:
                parsed = parse_markdown_config(str(file))
            except Exception as e:
                log.error("failed to parse markdown agent", {"path": str(file), "error": str(e)})
                continue

            name = _relative_without_ext(file, base)
            config: Dict[str, Any] = {"name": name, **parsed.data}
            if parsed.content:
                config["prompt"] = parsed.content

            try:
                validated = AgentConfig.model_validate(config)
            except Exception as e:
                log.error("invalid markdown agent config", {"path": str(file), "error": str(e)})
                continue

            result[name] = validated.model_dump(exclude_none=True, by_alias=True)

    return result


class ConfigError(Exception):
    """Configuration error."""

    def __init__(self, path: str, message: str):
        self.path = path
        super().__init__(f"Config error in {path}: {message}")


class ConfigManager:
    """Configuration management.

    Loads configuration from multiple sources with proper precedence:
    1. Global config (~/.config/hotaru/hotaru.json)
    2. Project config (hotaru.json in project root)
    3. .hotaru directory configs
    4. Environment variable overrides
    5. Managed config (enterprise, highest priority)
    """

    _cache: Optional[Config] = None
    _directories: List[str] = []

    @classmethod
    def reset(cls) -> None:
        """Reset cached configuration."""
        cls._cache = None
        cls._directories = []

    @classmethod
    async def load(cls, directory: str = ".") -> Config:
        """Load configuration for a directory.

        Args:
            directory: Working directory

        Returns:
            Merged configuration
        """
        if cls._cache is not None:
            return cls._cache

        result: Dict[str, Any] = {}
        directories: List[str] = []

        # 1. Global config
        global_config_dir = GlobalPath.config()
        directories.append(global_config_dir)

        for filename in ["config.json", "hotaru.json", "hotaru.jsonc"]:
            filepath = os.path.join(global_config_dir, filename)
            data = _load_json_file(filepath)
            if data:
                result = _deep_merge(result, data)
                log.info("loaded global config", {"path": filepath})

        # 2. Project config (search up from directory)
        current = Path(directory).resolve()
        project_configs = []

        while current != current.parent:
            for filename in ["hotaru.json", "hotaru.jsonc"]:
                filepath = current / filename
                if filepath.exists():
                    project_configs.append(str(filepath))
            current = current.parent

        # Apply in reverse order (root first, then more specific)
        for filepath in reversed(project_configs):
            data = _load_json_file(filepath)
            if data:
                result = _deep_merge(result, data)
                log.info("loaded project config", {"path": filepath})

        # 3. .hotaru directory configs
        current = Path(directory).resolve()
        hotaru_dirs = []

        while current != current.parent:
            hotaru_dir = current / ".hotaru"
            if hotaru_dir.is_dir():
                hotaru_dirs.append(str(hotaru_dir))
                directories.append(str(hotaru_dir))
            current = current.parent

        # Also check home directory
        home_hotaru = Path.home() / ".hotaru"
        if home_hotaru.is_dir():
            hotaru_dirs.append(str(home_hotaru))
            directories.append(str(home_hotaru))

        for hotaru_dir in reversed(hotaru_dirs):
            for filename in ["hotaru.json", "hotaru.jsonc"]:
                filepath = os.path.join(hotaru_dir, filename)
                data = _load_json_file(filepath)
                if data:
                    result = _deep_merge(result, data)
                    log.info("loaded .hotaru config", {"path": filepath})

        # 3.5. Markdown agent configs from supported roots
        markdown_roots: List[str] = []

        def add_markdown_root(root: str) -> None:
            resolved = str(Path(root).resolve())
            if resolved in markdown_roots:
                return
            if not Path(resolved).is_dir():
                return
            markdown_roots.append(resolved)
            if resolved not in directories:
                directories.append(resolved)

        # Global roots
        add_markdown_root(global_config_dir)
        add_markdown_root(str(Path(GlobalPath.home()) / ".config" / "opencode"))
        add_markdown_root(str(Path(GlobalPath.home()) / ".opencode"))
        add_markdown_root(str(Path(GlobalPath.home()) / ".hotaru"))

        # Project roots from repo root -> cwd
        current = Path(directory).resolve()
        ancestors: List[Path] = []
        while True:
            ancestors.append(current)
            if current == current.parent:
                break
            current = current.parent

        for ancestor in reversed(ancestors):
            add_markdown_root(str(ancestor / ".opencode"))
            add_markdown_root(str(ancestor / ".hotaru"))

        for root in markdown_roots:
            agent_data = _load_agent_markdown_dir(root)
            if not agent_data:
                continue
            result.setdefault("agent", {})
            result["agent"] = _deep_merge(result["agent"], agent_data)
            log.info("loaded markdown agents", {"root": root, "count": len(agent_data)})

        # 4. Environment variable config
        env_config = os.environ.get("HOTARU_CONFIG_CONTENT")
        if env_config:
            try:
                data = json.loads(env_config)
                result = _deep_merge(result, data)
                log.info("loaded config from HOTARU_CONFIG_CONTENT")
            except json.JSONDecodeError:
                log.error("failed to parse HOTARU_CONFIG_CONTENT")

        # 5. Managed config (highest priority)
        managed_dir = os.environ.get("HOTARU_TEST_MANAGED_CONFIG_DIR") or _get_managed_config_dir()
        if Path(managed_dir).exists():
            for filename in ["hotaru.json", "hotaru.jsonc"]:
                filepath = os.path.join(managed_dir, filename)
                data = _load_json_file(filepath)
                if data:
                    result = _deep_merge(result, data)
                    log.info("loaded managed config", {"path": filepath})

        # Set defaults
        if result.get("tools"):
            perms: Dict[str, str] = {}
            for tool_name, enabled in result["tools"].items():
                action = "allow" if enabled else "deny"
                perms[permission_for_tool(tool_name)] = action
            permission = result.get("permission")
            if isinstance(permission, str):
                permission = {"*": permission}
            result["permission"] = _deep_merge(perms, permission or {})

        if not result.get("username"):
            import getpass
            result["username"] = getpass.getuser()

        # Ensure required fields exist
        result.setdefault("agent", {})
        result.setdefault("command", {})
        result.setdefault("plugin", [])

        cls._directories = directories
        cls._cache = Config.model_validate(result)
        return cls._cache

    @classmethod
    async def get(cls) -> Config:
        """Get cached configuration."""
        if cls._cache is None:
            return await cls.load()
        return cls._cache

    @classmethod
    def directories(cls) -> List[str]:
        """Get configuration directories."""
        return cls._directories.copy()

    @classmethod
    async def update_global(cls, updates: Dict[str, Any]) -> Config:
        """Update global configuration.

        Args:
            updates: Configuration updates to apply

        Returns:
            Updated configuration
        """
        filepath = os.path.join(GlobalPath.config(), "hotaru.json")

        existing = _load_json_file(filepath)
        merged = _deep_merge(existing, updates)

        # Ensure directory exists
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(merged, f, indent=2)

        log.info("updated global config", {"path": filepath})

        # Reset cache
        cls.reset()

        return await cls.load()
