"""Configuration management.

Loads and merges configuration from multiple sources with proper precedence.
"""

import json
import os
from contextvars import ContextVar, Token
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config_loader import deep_merge, load_json_file
from .config_markdown import parse_markdown_config
from .config_schema import (
    AgentConfig,
    CommandConfig,
    CompactionConfig,
    Config,
    CustomModelConfig,
    ExperimentalConfig,
    LoggingConfig,
    McpConfig,
    McpLocalConfig,
    McpRemoteConfig,
    PermissionMemoryScope,
    ProviderConfig,
    ServerConfig,
    SkillsConfig,
    TuiConfig,
)
from .global_paths import GlobalPath
from ..permission.constants import permission_for_tool
from ..util.log import Log

log = Log.create({"service": "config"})

# Re-export schema types for backward compatibility
__all__ = [
    "AgentConfig",
    "CommandConfig",
    "CompactionConfig",
    "Config",
    "ConfigError",
    "ConfigManager",
    "CustomModelConfig",
    "ExperimentalConfig",
    "LoggingConfig",
    "McpConfig",
    "McpLocalConfig",
    "McpRemoteConfig",
    "PermissionMemoryScope",
    "ProviderConfig",
    "ServerConfig",
    "SkillsConfig",
    "TuiConfig",
]


def _get_managed_config_dir() -> str:
    """Get platform-specific managed config directory."""
    import platform
    system = platform.system()

    if system == "Darwin":
        return "/Library/Application Support/hotaru"
    if system == "Windows":
        program_data = os.environ.get("ProgramData", "C:\\ProgramData")
        return os.path.join(program_data, "hotaru")
    return "/etc/hotaru"


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


_config_var: ContextVar['ConfigManager'] = ContextVar('_config_var')


class ConfigManager:
    """Configuration management.

    Instance-based with ContextVar for scoping. Class methods delegate
    to the current instance so existing callers work unchanged.

    Loads configuration from multiple sources with proper precedence:
    1. Global config (~/.config/hotaru/hotaru.json)
    2. Project config (hotaru.json in project root)
    3. .hotaru directory configs
    4. Environment variable overrides
    5. Managed config (enterprise, highest priority)
    """

    def __init__(self) -> None:
        self._cache: Optional[Config] = None
        self._directories: List[str] = []

    # -- ContextVar plumbing --

    @classmethod
    def current(cls) -> 'ConfigManager':
        try:
            return _config_var.get()
        except LookupError:
            # Fallback: create a default instance for backward compat
            instance = cls()
            _config_var.set(instance)
            return instance

    @classmethod
    def provide(cls, instance: 'ConfigManager') -> Token['ConfigManager']:
        return _config_var.set(instance)

    @classmethod
    def restore(cls, token: Token['ConfigManager']) -> None:
        _config_var.reset(token)

    # -- Public API (class methods delegate to current instance) --

    @classmethod
    def reset(cls) -> None:
        """Reset cached configuration."""
        inst = cls.current()
        inst._cache = None
        inst._directories = []

    @classmethod
    async def load(cls, directory: str = ".") -> Config:
        return await cls.current()._load(directory)

    @classmethod
    async def get(cls) -> Config:
        inst = cls.current()
        if inst._cache is None:
            return await inst._load()
        return inst._cache

    @classmethod
    def directories(cls) -> List[str]:
        return cls.current()._directories.copy()

    @classmethod
    async def update_global(cls, updates: Dict[str, Any]) -> Config:
        return await cls.current()._update_global(updates)

    # -- Instance methods --

    async def _load(self, directory: str = ".") -> Config:
        if self._cache is not None:
            return self._cache

        result: Dict[str, Any] = {}
        directories: List[str] = []

        # 1. Global config
        global_config_dir = GlobalPath.config()
        directories.append(global_config_dir)

        for filename in ["config.json", "hotaru.json", "hotaru.jsonc"]:
            filepath = os.path.join(global_config_dir, filename)
            data = load_json_file(filepath)
            if data:
                result = deep_merge(result, data)
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
            data = load_json_file(filepath)
            if data:
                result = deep_merge(result, data)
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
                data = load_json_file(filepath)
                if data:
                    result = deep_merge(result, data)
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
            result["agent"] = deep_merge(result["agent"], agent_data)
            log.info("loaded markdown agents", {"root": root, "count": len(agent_data)})

        # 4. Environment variable config
        env_config = os.environ.get("HOTARU_CONFIG_CONTENT")
        if env_config:
            try:
                data = json.loads(env_config)
                result = deep_merge(result, data)
                log.info("loaded config from HOTARU_CONFIG_CONTENT")
            except json.JSONDecodeError:
                log.error("failed to parse HOTARU_CONFIG_CONTENT")

        # 5. Managed config (highest priority)
        managed_dir = os.environ.get("HOTARU_TEST_MANAGED_CONFIG_DIR") or _get_managed_config_dir()
        if Path(managed_dir).exists():
            for filename in ["hotaru.json", "hotaru.jsonc"]:
                filepath = os.path.join(managed_dir, filename)
                data = load_json_file(filepath)
                if data:
                    result = deep_merge(result, data)
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
            result["permission"] = deep_merge(perms, permission or {})

        if not result.get("username"):
            import getpass
            result["username"] = getpass.getuser()

        # Ensure required fields exist
        result.setdefault("agent", {})
        result.setdefault("command", {})
        result.setdefault("plugin", [])

        self._directories = directories
        self._cache = Config.model_validate(result)
        return self._cache

    async def _update_global(self, updates: Dict[str, Any]) -> Config:
        filepath = os.path.join(GlobalPath.config(), "hotaru.json")

        existing = load_json_file(filepath)
        merged = deep_merge(existing, updates)

        Path(filepath).parent.mkdir(parents=True, exist_ok=True)

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(merged, f, indent=2)

        log.info("updated global config", {"path": filepath})

        self._cache = None
        self._directories = []

        return await self._load()
