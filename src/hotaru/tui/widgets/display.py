"""Display widgets: ToolDisplay, CodeBlock, DiffDisplay."""

from typing import Any, Callable, Dict, List, Optional

from textual.widgets import Static
from rich.syntax import Syntax
from rich.text import Text

from ..theme import ThemeManager


class ToolDisplay(Static):
    """Widget for displaying tool execution inline.

    Renders tool-specific icons, descriptions, and status indicators
    following the OpenCode InlineTool/BlockTool pattern.
    """

    MAX_OUTPUT_LINES = 10
    MAX_BLOCK_LINES = 40

    def __init__(
        self,
        part: Optional[Dict[str, Any]] = None,
        show_details: bool = True,
        on_open_session: Optional[Callable[[str], None]] = None,
        *,
        tool_name: str = "",
        tool_id: str = "",
        status: str = "running",
        input_data: Optional[Dict[str, Any]] = None,
        output: Optional[str] = None,
        error: Optional[str] = None,
        title: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.show_details = show_details
        self.on_open_session = on_open_session
        if part is None:
            part = {
                "id": tool_id or f"tool-{tool_name}",
                "type": "tool",
                "tool": tool_name or "tool",
                "call_id": tool_id,
                "state": {
                    "status": status,
                    "input": input_data or {},
                    "output": output,
                    "error": error,
                    "title": title,
                    "metadata": metadata or {},
                },
            }
        self.part = part

    def set_part(self, part: Dict[str, Any]) -> None:
        self.part = part

    def render(self) -> Text:
        theme = ThemeManager.get_theme()
        status = self._status()
        if not self.show_details and status == "completed" and not self._error():
            return Text("")
        renderer = {
            "bash": self._render_bash,
            "read": self._render_read,
            "write": self._render_write,
            "edit": self._render_edit,
            "glob": self._render_glob,
            "grep": self._render_grep,
            "list": self._render_list,
            "webfetch": self._render_webfetch,
            "codesearch": self._render_codesearch,
            "websearch": self._render_websearch,
            "task": self._render_task,
            "apply_patch": self._render_apply_patch,
            "todowrite": self._render_todowrite,
            "question": self._render_question,
            "skill": self._render_skill,
        }.get(self._tool_name(), self._render_generic)
        return renderer(theme)

    def on_click(self) -> None:
        if self._tool_name() != "task" or not self.on_open_session:
            return
        metadata = self._metadata()
        session_id = metadata.get("session_id") or metadata.get("sessionId")
        if isinstance(session_id, str) and session_id:
            self.on_open_session(session_id)

    def _tool_name(self) -> str:
        return str(self.part.get("tool") or "tool")

    def _state(self) -> Dict[str, Any]:
        state = self.part.get("state")
        return state if isinstance(state, dict) else {}

    def _status(self) -> str:
        return str(self._state().get("status") or "pending")

    def _input(self) -> Dict[str, Any]:
        value = self._state().get("input")
        return value if isinstance(value, dict) else {}

    def _metadata(self) -> Dict[str, Any]:
        value = self._state().get("metadata")
        return value if isinstance(value, dict) else {}

    def _title(self) -> str:
        title = self._state().get("title")
        return str(title or "")

    def _output(self) -> str:
        value = self._state().get("output")
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        return str(value)

    def _error(self) -> str:
        value = self._state().get("error")
        return str(value or "")

    def _is_running(self) -> bool:
        return self._status() in {"pending", "running"}

    def _inline(self, theme, *, icon: str, pending: str, done: str) -> Text:
        text = Text()
        if self._is_running():
            text.append("~ ", style=theme.text_muted)
            text.append(pending, style=theme.text_muted)
            return text
        text.append(f"{icon} ", style=theme.text_muted)
        text.append(done, style=theme.text_muted)
        error = self._error()
        if error:
            text.append(f"\n{error}", style=theme.error)
        return text

    def _block(self, theme, title: str, lines: List[str], *, show_spinner: bool = False) -> Text:
        text = Text()
        if show_spinner:
            text.append("~ ", style=theme.text_muted)
            text.append(title, style=theme.text_muted)
        else:
            text.append(title, style=theme.text_muted)
        for line in lines[: self.MAX_BLOCK_LINES]:
            text.append(f"\n{line}", style=theme.text_muted)
        if len(lines) > self.MAX_BLOCK_LINES:
            text.append(f"\n... {len(lines) - self.MAX_BLOCK_LINES} more lines", style=theme.text_muted)
        error = self._error()
        if error:
            text.append(f"\n{error}", style=theme.error)
        return text

    @staticmethod
    def _pick(data: Dict[str, Any], *keys: str, default: str = "") -> str:
        for key in keys:
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
        return default

    # -- Tool-specific renderers --

    def _render_bash(self, theme) -> Text:
        input_data = self._input()
        metadata = self._metadata()
        command = self._pick(input_data, "command")
        description = self._title() or self._pick(metadata, "description") or command or "Shell command"
        output = self._pick(metadata, "output") or self._output()
        if output and self.show_details:
            lines = [f"$ {command}"] if command else []
            shown, remaining = self._limit_lines(output, self.MAX_OUTPUT_LINES)
            lines.extend(shown)
            if remaining > 0:
                lines.append(f"... {remaining} more lines")
            return self._block(theme, f"# {description}", lines, show_spinner=self._is_running())
        return self._inline(theme, icon="$", pending="Writing command...", done=command or description)

    def _render_read(self, theme) -> Text:
        input_data = self._input()
        file_path = self._pick(input_data, "file_path", "filePath", "path")
        return self._inline(theme, icon="\u2192", pending="Reading file...", done=f"Read {file_path}".strip())

    def _render_write(self, theme) -> Text:
        input_data = self._input()
        metadata = self._metadata()
        file_path = self._pick(input_data, "file_path", "filePath", "path")
        if self.show_details and isinstance(metadata.get("diagnostics"), dict):
            content = self._pick(input_data, "content")
            lines = content.splitlines() if content else ["Wrote file successfully."]
            return self._block(theme, f"# Wrote {file_path}", lines)
        return self._inline(theme, icon="\u2190", pending="Preparing write...", done=f"Write {file_path}".strip())

    def _render_edit(self, theme) -> Text:
        input_data = self._input()
        metadata = self._metadata()
        file_path = self._pick(input_data, "file_path", "filePath", "path")
        diff = self._pick(metadata, "diff")
        if self.show_details and diff:
            shown, remaining = self._limit_lines(diff, self.MAX_OUTPUT_LINES)
            if remaining > 0:
                shown.append(f"... {remaining} more lines")
            return self._block(theme, f"\u2190 Edit {file_path}", shown)
        return self._inline(theme, icon="\u2190", pending="Preparing edit...", done=f"Edit {file_path}".strip())

    def _render_glob(self, theme) -> Text:
        input_data = self._input()
        metadata = self._metadata()
        pattern = self._pick(input_data, "pattern", default="*")
        count = metadata.get("count")
        suffix = f" ({count} matches)" if isinstance(count, int) else ""
        return self._inline(theme, icon="\u2731", pending="Finding files...", done=f'Glob "{pattern}"{suffix}')

    def _render_grep(self, theme) -> Text:
        input_data = self._input()
        metadata = self._metadata()
        pattern = self._pick(input_data, "pattern", default="")
        matches = metadata.get("matches")
        suffix = f" ({matches} matches)" if isinstance(matches, int) else ""
        return self._inline(theme, icon="\u2731", pending="Searching content...", done=f'Grep "{pattern}"{suffix}')

    def _render_list(self, theme) -> Text:
        input_data = self._input()
        path = self._pick(input_data, "path", default=".")
        return self._inline(theme, icon="\u2192", pending="Listing directory...", done=f"List {path}")

    def _render_webfetch(self, theme) -> Text:
        input_data = self._input()
        url = self._pick(input_data, "url")
        return self._inline(theme, icon="%", pending="Fetching from the web...", done=f"WebFetch {url}".strip())

    def _render_codesearch(self, theme) -> Text:
        input_data = self._input()
        query = self._pick(input_data, "query")
        return self._inline(theme, icon="\u25c7", pending="Searching code...", done=f'Code search "{query}"')

    def _render_websearch(self, theme) -> Text:
        input_data = self._input()
        query = self._pick(input_data, "query")
        return self._inline(theme, icon="\u25c8", pending="Searching web...", done=f'Web search "{query}"')

    # -- Remaining renderers --

    def _render_task(self, theme) -> Text:
        input_data = self._input()
        metadata = self._metadata()
        description = self._pick(input_data, "description")
        subagent = self._pick(input_data, "subagent_type", "subagentType", default="subagent")
        if not self.show_details:
            return self._inline(theme, icon="#", pending="Delegating...", done=f"{subagent} Task {description}".strip())
        session_id = self._pick(metadata, "session_id", "sessionId")
        lines = []
        if description:
            lines.append(description)
        if session_id:
            lines.append(f"session: {session_id} (click to open)")
        title = f"# {subagent.capitalize()} Task"
        return self._block(theme, title, lines or ["Delegating..."], show_spinner=self._is_running())

    def _render_apply_patch(self, theme) -> Text:
        metadata = self._metadata()
        files = metadata.get("files")
        if self.show_details and isinstance(files, list) and files:
            lines: List[str] = []
            for item in files[:10]:
                if not isinstance(item, dict):
                    continue
                rel = self._pick(item, "relativePath", "relative_path", "filePath", "file_path")
                change_type = self._pick(item, "type", default="update")
                additions = item.get("additions", 0)
                deletions = item.get("deletions", 0)
                lines.append(f"{change_type}: {rel} (+{additions}/-{deletions})")
            return self._block(theme, "# Patch", lines)
        return self._inline(theme, icon="%", pending="Preparing patch...", done="Patch")

    def _render_todowrite(self, theme) -> Text:
        metadata = self._metadata()
        todos = metadata.get("todos")
        if self.show_details and isinstance(todos, list) and todos:
            lines: List[str] = []
            for item in todos[:15]:
                if not isinstance(item, dict):
                    continue
                status = str(item.get("status") or "pending")
                content = str(item.get("content") or "")
                lines.append(f"[{status}] {content}")
            return self._block(theme, "# Todos", lines)
        return self._inline(theme, icon="\u2699", pending="Updating todos...", done="Updated todos")

    def _render_question(self, theme) -> Text:
        input_data = self._input()
        metadata = self._metadata()
        questions = input_data.get("questions")
        answers = metadata.get("answers")
        if self.show_details and isinstance(questions, list) and isinstance(answers, list):
            lines: List[str] = []
            for idx, question in enumerate(questions):
                if not isinstance(question, dict):
                    continue
                text = str(question.get("question") or "")
                answer = answers[idx] if idx < len(answers) else []
                if isinstance(answer, list):
                    answer_text = ", ".join(str(a) for a in answer) if answer else "(no answer)"
                else:
                    answer_text = str(answer)
                lines.append(text)
                lines.append(f"  -> {answer_text}")
            return self._block(theme, "# Questions", lines)
        count = len(questions) if isinstance(questions, list) else 0
        return self._inline(theme, icon="\u2192", pending="Asking questions...", done=f"Asked {count} question(s)")

    def _render_skill(self, theme) -> Text:
        input_data = self._input()
        name = self._pick(input_data, "name", "skill")
        return self._inline(theme, icon="\u2192", pending="Loading skill...", done=f'Skill "{name}"')

    def _render_generic(self, theme) -> Text:
        summary = self._format_input_summary(self._input())
        return self._inline(theme, icon="\u2699", pending=f"Running {self._tool_name()}...", done=f"{self._tool_name()} {summary}".strip())

    @staticmethod
    def _format_input_summary(input_data: Dict[str, Any]) -> str:
        parts = []
        for key, value in input_data.items():
            if isinstance(value, str) and len(value) < 60:
                parts.append(f"{key}={value}")
            elif isinstance(value, (int, float, bool)):
                parts.append(f"{key}={value}")
        if parts:
            return f"[{', '.join(parts[:3])}]"
        return ""

    @staticmethod
    def _limit_lines(text: str, max_lines: int) -> tuple[List[str], int]:
        lines = text.splitlines()
        shown = lines[:max_lines]
        remaining = max(0, len(lines) - len(shown))
        return shown, remaining


class CodeBlock(Static):
    """Widget for displaying syntax-highlighted code."""

    def __init__(
        self,
        code: str,
        language: str = "python",
        line_numbers: bool = True,
        **kwargs
    ) -> None:
        super().__init__(**kwargs)
        self.code = code
        self.language = language
        self.line_numbers = line_numbers

    def render(self) -> Syntax:
        """Render the code block."""
        theme = ThemeManager.get_theme()
        theme_name = "monokai" if ThemeManager.get_mode() == "dark" else "github-light"
        return Syntax(
            self.code,
            self.language,
            theme=theme_name,
            line_numbers=self.line_numbers,
            word_wrap=True,
        )


class DiffDisplay(Static):
    """Widget for displaying file diffs."""

    def __init__(
        self,
        diff_content: str,
        file_path: Optional[str] = None,
        **kwargs
    ) -> None:
        super().__init__(**kwargs)
        self.diff_content = diff_content
        self.file_path = file_path

    def render(self) -> Text:
        """Render the diff display."""
        theme = ThemeManager.get_theme()
        text = Text()
        for line in self.diff_content.split("\n"):
            if line.startswith("+") and not line.startswith("+++"):
                text.append(line + "\n", style=f"on {theme.diff_added_bg} {theme.diff_added}")
            elif line.startswith("-") and not line.startswith("---"):
                text.append(line + "\n", style=f"on {theme.diff_removed_bg} {theme.diff_removed}")
            elif line.startswith("@@"):
                text.append(line + "\n", style=f"bold {theme.info}")
            else:
                text.append(line + "\n", style=theme.text)
        return text
