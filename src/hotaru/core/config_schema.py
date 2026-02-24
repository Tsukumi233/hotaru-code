"""Configuration schema — Pydantic models for hotaru config files."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    """Provider configuration."""
    type: Optional[Literal["openai", "anthropic"]] = None
    name: Optional[str] = None
    models: Optional[Dict[str, CustomModelConfig]] = None
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


class LoggingConfig(BaseModel):
    """Logging configuration."""
    level: Optional[str] = None
    format: Optional[Literal["kv", "json", "pretty"]] = None
    console: Optional[bool] = None
    file: Optional[bool] = None
    access_log: Optional[bool] = Field(None, alias="accessLog")
    dev_file: Optional[bool] = Field(None, alias="devFile")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


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
    logging: Optional[LoggingConfig] = None

    model: Optional[str] = None
    small_model: Optional[str] = None
    default_agent: Optional[str] = None
    username: Optional[str] = None

    provider: Optional[Dict[str, ProviderConfig]] = None
    disabled_providers: Optional[List[str]] = None
    enabled_providers: Optional[List[str]] = None

    agent: Optional[Dict[str, AgentConfig]] = None
    command: Optional[Dict[str, CommandConfig]] = None
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    mcp: Optional[Dict[str, McpConfig]] = None

    permission: Optional[Union[str, Dict[str, Any]]] = None
    permission_memory_scope: PermissionMemoryScope = PermissionMemoryScope.SESSION
    tools: Optional[Dict[str, bool]] = None
    strict_permissions: Optional[bool] = None
    continue_loop_on_deny: bool = False
    experimental: ExperimentalConfig = Field(default_factory=ExperimentalConfig)

    server: Optional[ServerConfig] = None
    tui: Optional[TuiConfig] = None

    plugin: Optional[List[str]] = None
    instructions: Optional[List[str]] = None
    snapshot: Optional[bool] = None
    share: Optional[Literal["manual", "auto", "disabled"]] = None
    autoupdate: Optional[Union[bool, Literal["notify"]]] = None
    compaction: Optional[CompactionConfig] = None

    lsp: Optional[Union[Literal[False], Dict[str, Any]]] = None
    formatter: Optional[Union[Literal[False], Dict[str, Any]]] = None

    model_config = ConfigDict(extra="forbid", populate_by_name=True)
