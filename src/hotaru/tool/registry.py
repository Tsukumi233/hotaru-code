"""Tool registry for built-in and dynamically loaded tools."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ..core.config import ConfigManager
from ..util.log import Log

if TYPE_CHECKING:
    from ..runtime import AppContext
from .apply_patch import ApplyPatchTool
from .bash import BashTool
from .batch import BatchTool
from .codesearch import CodeSearchTool
from .edit import EditTool
from .glob import GlobTool
from .grep import GrepTool
from .list import LsTool
from .lsp import LspTool
from .multiedit import MultiEditTool
from .permission_guard import PermissionGuard
from .plan import PlanEnterTool, PlanExitTool
from .question import QuestionTool
from .read import ReadTool
from .schema import strictify_schema
from .skill import SkillTool, build_skill_description
from .task import TaskTool, build_task_description
from .todo import TodoReadTool, TodoWriteTool
from .tool import ToolContext, ToolInfo, ToolResult
from .truncation import start_cleanup_task
from .webfetch import WebFetchTool
from .websearch import WebSearchTool
from .write import WriteTool

log = Log.create({"service": "tool.registry"})


class ToolRegistry:
    """Central registry for all available tools."""

    def __init__(self) -> None:
        self._tools: Optional[Dict[str, ToolInfo]] = None
        self._initialized: bool = False

    async def init(self) -> None:
        """Eagerly initialize the tool registry during startup."""
        self._initialize()

    @staticmethod
    def _load_custom_tools() -> Dict[str, ToolInfo]:
        custom: Dict[str, ToolInfo] = {}
        dirs = ConfigManager.directories()
        if not dirs:
            dirs = [str(Path.cwd())]
        seen_paths = set()

        for root in dirs:
            root_path = Path(root)
            if not root_path.exists():
                continue

            for pattern in ("tool/*.py", "tools/*.py"):
                for file_path in root_path.glob(pattern):
                    resolved = str(file_path.resolve())
                    if resolved in seen_paths:
                        continue
                    seen_paths.add(resolved)
                    try:
                        loaded = ToolRegistry._load_tools_from_module(file_path)
                    except Exception as exc:
                        log.warn("failed loading custom tool module", {"file": resolved, "error": str(exc)})
                        continue
                    custom.update({tool.id: tool for tool in loaded})

        return custom

    @staticmethod
    def _load_tools_from_module(file_path: Path) -> List[ToolInfo]:
        module_name = f"_hotaru_custom_tool_{file_path.stem}_{abs(hash(str(file_path)))}"
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            return []
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        discovered: List[ToolInfo] = []
        candidates = []

        if hasattr(module, "TOOLS"):
            tools_obj = getattr(module, "TOOLS")
            if isinstance(tools_obj, dict):
                candidates.extend(tools_obj.values())
            elif isinstance(tools_obj, list):
                candidates.extend(tools_obj)

        if hasattr(module, "tool"):
            candidates.append(getattr(module, "tool"))
        if hasattr(module, "Tool"):
            candidates.append(getattr(module, "Tool"))

        if hasattr(module, "register_tools") and callable(getattr(module, "register_tools")):
            returned = getattr(module, "register_tools")()
            if isinstance(returned, dict):
                candidates.extend(returned.values())
            elif isinstance(returned, list):
                candidates.extend(returned)

        for item in candidates:
            if isinstance(item, ToolInfo):
                discovered.append(item)
                continue
            if all(hasattr(item, attr) for attr in ("id", "description", "parameters_type", "execute")):
                discovered.append(item)

        return discovered

    def _initialize(self) -> Dict[str, ToolInfo]:
        if self._tools is not None:
            return self._tools

        tools: Dict[str, ToolInfo] = {}
        builtin_tools: List[ToolInfo] = [
            BashTool,
            ReadTool,
            GlobTool,
            GrepTool,
            EditTool,
            WriteTool,
            LsTool,
            TaskTool,
            SkillTool,
            WebFetchTool,
            TodoWriteTool,
            TodoReadTool,
            WebSearchTool,
            CodeSearchTool,
            ApplyPatchTool,
            MultiEditTool,
            BatchTool,
            QuestionTool,
            PlanEnterTool,
            PlanExitTool,
            LspTool,
        ]

        for tool in builtin_tools:
            tools[tool.id] = tool

        custom_tools = self._load_custom_tools()
        tools.update(custom_tools)

        start_cleanup_task()

        self._tools = tools
        self._initialized = True
        return tools

    def _all(self) -> Dict[str, ToolInfo]:
        return self._initialize()

    @staticmethod
    def _apply_patch_enabled_for_model(model_id: str) -> bool:
        lowered = model_id.lower()
        return "gpt-" in lowered and "oss" not in lowered and "gpt-4" not in lowered

    async def _tool_enabled(
        self,
        *,
        tool_id: str,
        provider_id: Optional[str],
        model_id: Optional[str],
    ) -> bool:
        config = await ConfigManager.get()
        experimental = config.experimental

        if tool_id in {"codesearch", "websearch"}:
            if provider_id == "opencode":
                return True
            return experimental.enable_exa

        if tool_id == "batch":
            return experimental.batch_tool

        if tool_id == "lsp":
            return experimental.lsp_tool

        if tool_id == "apply_patch":
            return self._apply_patch_enabled_for_model(model_id or "")

        if tool_id in {"edit", "write"}:
            use_patch = self._apply_patch_enabled_for_model(model_id or "")
            return not use_patch

        return True

    def get(self, tool_id: str) -> Optional[ToolInfo]:
        return self._all().get(tool_id)

    def list(self) -> List[ToolInfo]:
        return list(self._all().values())

    def ids(
        self,
        *,
        provider_id: Optional[str] = None,
        model_id: Optional[str] = None,
    ) -> List[str]:
        return list(self._all().keys())

    def register(self, tool: ToolInfo) -> None:
        self._all()[tool.id] = tool

    async def execute(self, tool_id: str, args: Any, ctx: ToolContext) -> ToolResult:
        tool = self.get(tool_id)
        if tool is None:
            raise ValueError(f"Unknown tool: {tool_id}")

        try:
            parsed = tool.parameters_type.model_validate(args)
        except Exception as e:
            raise ValueError(f"Invalid tool input: {e}") from e

        permissions = await tool.permissions(parsed, ctx)
        await PermissionGuard.check(permissions, ctx)
        return await tool.execute(parsed, ctx)

    async def get_tool_definitions(
        self,
        *,
        app: AppContext,
        caller_agent: Optional[str] = None,
        provider_id: Optional[str] = None,
        model_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        tools = self._all()
        definitions = []

        for tool in tools.values():
            if not await self._tool_enabled(tool_id=tool.id, provider_id=provider_id, model_id=model_id):
                continue

            schema = tool.parameters_type.model_json_schema()
            schema.pop("title", None)
            schema = strictify_schema(schema)

            description = tool.description
            if tool.id == "skill":
                try:
                    description = await build_skill_description(caller_agent, skills=app.skills, agents=app.agents)
                except Exception:
                    pass
            elif tool.id == "task":
                try:
                    description = await build_task_description(caller_agent=caller_agent, agents=app.agents)
                except Exception:
                    pass

            definitions.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.id,
                        "description": description,
                        "parameters": schema,
                    },
                }
            )

        return definitions

    def reset(self) -> None:
        self._tools = None
        self._initialized = False
