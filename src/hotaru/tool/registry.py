"""Tool registry for built-in and dynamically loaded tools."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ..core.config import ConfigManager
from ..util.log import Log
from .apply_patch import ApplyPatchTool
from .bash import BashTool
from .batch import BatchTool
from .codesearch import CodeSearchTool
from .edit import EditTool
from .glob import GlobTool
from .grep import GrepTool
from .invalid import InvalidTool
from .list import LsTool
from .lsp import LspTool
from .multiedit import MultiEditTool
from .plan import PlanEnterTool, PlanExitTool
from .question import QuestionTool
from .read import ReadTool
from .skill import SkillTool, build_skill_description
from .task import TaskTool, build_task_description
from .todo import TodoReadTool, TodoWriteTool
from .tool import ToolInfo
from .truncation import start_cleanup_task
from .webfetch import WebFetchTool
from .websearch import WebSearchTool
from .write import WriteTool

log = Log.create({"service": "tool.registry"})


class ToolRegistry:
    """Central registry for all available tools."""

    _tools: Optional[Dict[str, ToolInfo]] = None
    _initialized: bool = False

    @classmethod
    def _load_custom_tools(cls) -> Dict[str, ToolInfo]:
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
                        loaded = cls._load_tools_from_module(file_path)
                    except Exception as exc:
                        log.warn("failed loading custom tool module", {"file": resolved, "error": str(exc)})
                        continue
                    custom.update({tool.id: tool for tool in loaded})

        return custom

    @classmethod
    def _load_tools_from_module(cls, file_path: Path) -> List[ToolInfo]:
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

    @classmethod
    def _initialize(cls) -> Dict[str, ToolInfo]:
        if cls._tools is not None:
            return cls._tools

        tools: Dict[str, ToolInfo] = {}
        builtin_tools: List[ToolInfo] = [
            InvalidTool,
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

        custom_tools = cls._load_custom_tools()
        tools.update(custom_tools)

        start_cleanup_task()

        cls._tools = tools
        cls._initialized = True
        return tools

    @classmethod
    def _all(cls) -> Dict[str, ToolInfo]:
        return cls._initialize()

    @classmethod
    def _apply_patch_enabled_for_model(cls, model_id: str) -> bool:
        lowered = model_id.lower()
        return "gpt-" in lowered and "oss" not in lowered and "gpt-4" not in lowered

    @classmethod
    async def _tool_enabled(
        cls,
        *,
        tool_id: str,
        provider_id: Optional[str],
        model_id: Optional[str],
    ) -> bool:
        config = await ConfigManager.get()
        experimental_raw = getattr(config, "experimental", {}) or {}
        if hasattr(experimental_raw, "model_dump"):
            experimental = experimental_raw.model_dump(exclude_none=True)
        elif isinstance(experimental_raw, dict):
            experimental = experimental_raw
        else:
            experimental = {}

        if tool_id in {"codesearch", "websearch"}:
            if provider_id == "opencode":
                return True
            return bool(experimental.get("enable_exa", False))

        if tool_id == "batch":
            return bool(experimental.get("batch_tool", False))

        if tool_id == "lsp":
            return bool(experimental.get("lsp_tool", False))

        if tool_id == "apply_patch":
            return cls._apply_patch_enabled_for_model(model_id or "")

        if tool_id in {"edit", "write"}:
            use_patch = cls._apply_patch_enabled_for_model(model_id or "")
            return not use_patch

        return True

    @classmethod
    def get(cls, tool_id: str) -> Optional[ToolInfo]:
        tools = cls._all()
        return tools.get(tool_id)

    @classmethod
    def list(cls) -> List[ToolInfo]:
        tools = cls._all()
        return list(tools.values())

    @classmethod
    def ids(
        cls,
        *,
        provider_id: Optional[str] = None,
        model_id: Optional[str] = None,
    ) -> List[str]:
        tools = cls._all()
        return list(tools.keys())

    @classmethod
    def register(cls, tool: ToolInfo) -> None:
        tools = cls._all()
        tools[tool.id] = tool

    @classmethod
    async def get_tool_definitions(
        cls,
        *,
        caller_agent: Optional[str] = None,
        provider_id: Optional[str] = None,
        model_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        tools = cls._all()
        definitions = []

        for tool in tools.values():
            if not await cls._tool_enabled(tool_id=tool.id, provider_id=provider_id, model_id=model_id):
                continue

            schema = tool.parameters_type.model_json_schema()
            schema.pop("title", None)

            description = tool.description
            if tool.id == "skill":
                try:
                    description = await build_skill_description(caller_agent)
                except Exception:
                    pass
            elif tool.id == "task":
                try:
                    description = await build_task_description(caller_agent=caller_agent)
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

    @classmethod
    def reset(cls) -> None:
        cls._tools = None
        cls._initialized = False
