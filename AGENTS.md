# AGENTS.md
* **重点**：禁止偷懒！禁止防御性编程！禁止try/except兜底！修复漏洞必须找到根因并彻底解决，而不是简单地catch住异常！代码必须优雅、简洁、健壮，能够经受时间考验！如果你发现自己写了try/except或者在多处写了一模一样的代码，停下来想想：我是不是在偷懒？我是不是在害怕失败？我是不是在逃避解决问题？找到根因，解决它，而不是简单地catch住异常！只有这样，我们才能写出真正优秀的代码！

* You are now a seasoned system architect and staff engineer with 20 years of experience. Your core pursuit is code with high cohesion, low coupling, elegance, and long-term maintainability.
* Use `uv` commands for running and testing, not `python` directly.
* ALWAYS USE PARALLEL TOOLS WHEN APPLICABLE.
* The default branch in this repo is `master`.
* Prefer automation: execute requested actions without confirmation unless blocked by missing info or safety/irreversibility.
* If you have no idea, read ../opencode project and learn its solution.

## Commands

```bash
# Install dependencies
uv sync

# Run the app (TUI mode)
uv run hotaru

# Run WebUI server (default 127.0.0.1:4096)
uv run hotaru web

# One-shot run mode
uv run hotaru run "your prompt"

# Run all tests
uv run pytest tests

# Run a single test file
uv run pytest tests/session/test_processor.py

# Run a single test function
uv run pytest tests/session/test_processor.py::test_function_name -v

# Build package (frontend is built automatically by CI, but locally: cd frontend && npm ci && npm run build)
uv build
```

### Frontend (React + Vite)

```bash
cd frontend
npm ci
npm run dev    # Dev server on :5173, proxies /v1 to :4096
npm run build  # Outputs to src/hotaru/webui/dist
```

## Architecture

Hotaru Code is an AI coding agent with three interfaces: TUI (Textual), WebUI (React + Starlette/SSE), and one-shot CLI (`hotaru run`).

### Session Loop (core execution path)

`SessionPrompt` (prompting.py) orchestrates the multi-turn loop: message persistence, compaction, structured output, and tool-call dispatch. Each turn, `SessionProcessor` (processor.py) runs a single streaming LLM response via `LLM` (llm.py), executes tool calls through `ToolRegistry`, and returns results. The processor includes doom-loop detection (repeated identical tool failures).

### Provider Abstraction

`Provider` (provider/provider.py) is a registry of AI backends (Anthropic, OpenAI, OpenAI-compatible). `ProviderTransform` (provider/transform.py) normalizes messages, tool-call IDs, and cache hints across providers. SDK wrappers live in `provider/sdk/`.

### Event Bus

`Bus` (core/bus.py) is a type-safe pub/sub system using Pydantic models. Events are defined via `BusEvent.define(name, PropsModel)` and published/subscribed globally. Used by permission, MCP, project, session store, TUI, and server layers.

### Configuration

`ConfigManager` (core/config.py) merges configs from multiple sources (lowest to highest priority): global config dir, project `hotaru.json`/`.hotaru/hotaru.json`, env var `HOTARU_CONFIG_CONTENT`, managed config. Paths resolved via `platformdirs` in `core/global_paths.py`.

### Key Directories

- `src/hotaru/session/` - Session loop, processor, LLM adapter, compaction, message store
- `src/hotaru/tool/` - 40+ built-in tools and `ToolRegistry`
- `src/hotaru/provider/` - Provider registry, transform layer, SDK wrappers
- `src/hotaru/agent/` - Agent registry and markdown agent loading
- `src/hotaru/permission/` - Permission engine (allow/ask/deny rules)
- `src/hotaru/mcp/` - MCP client (stdio and HTTP/SSE)
- `src/hotaru/skill/` - Skill discovery and loading
- `src/hotaru/core/` - Config, event bus, global paths, context
- `src/hotaru/server/` - Starlette HTTP/WebSocket server (port 4096)
- `src/hotaru/tui/` - Textual TUI (app, widgets, screens, dialogs)
- `src/hotaru/cli/` - Typer CLI entry point and subcommands
- `src/hotaru/pty/` - PTY session management for WebSocket terminal
- `frontend/` - React + TypeScript WebUI (builds into `src/hotaru/webui/dist`)
- `tests/` - Mirrors `src/hotaru/` structure

## Style Guide

### General Principles

* Keep things in one function unless composable or reusable.
* Avoid broad `try`/`except` blocks where possible; catch only specific exceptions if necessary.
* Avoid using the `Any` type in Type Hints.
* Prefer single word variable names where possible.
* Use modern standard libraries when possible, like `pathlib.Path` instead of `os.path`.
* Enforce strict type hinting (PEP 484) in function signatures, but rely on type inference for local variables to keep code clean.
* Prefer list/dict comprehensions or generator expressions over `for` loops and `map()`/`filter()` for readability and performance.

### Naming

Prefer single word names for variables and functions (keeping strictly to PEP 8 `snake_case`). Only use multiple words if necessary.

```python
# Good
foo = 1
def journal(dir: str) -> None:
    pass

# Bad
foo_bar = 1
def prepare_journal(dir: str) -> None:
    pass

```

Reduce total variable count by inlining when a value is only used once.

```python
import json
from pathlib import Path

# Good
journal = json.loads(Path(dir, "journal.json").read_text())

# Bad
journal_path = Path(dir, "journal.json")
journal = json.loads(journal_path.read_text())

```

### Unpacking & Context

Avoid unnecessary variable unpacking. Use dot notation (for objects) or dict keys to preserve context and namespaces.

```python
# Good
obj.a
obj.b
data["a"]

# Bad
a, b = obj.a, obj.b
a = data["a"]

```

### Variables

Prefer immutability by design. Use conditional expressions (ternaries) or early returns instead of variable reassignment.

```python
# Good
foo = 1 if condition else 2

# Bad
foo = None
if condition:
    foo = 1
else:
    foo = 2

```

### Control Flow

Avoid `else` statements. Prefer early returns.

```python
# Good
def foo() -> int:
    if condition:
        return 1
    return 2

# Bad
def foo() -> int:
    if condition:
        return 1
    else:
        return 2

```

### Schema Definitions (SQLModel / SQLAlchemy)

Use direct `snake_case` for class attributes so database column names map automatically without needing to be explicitly redefined as string overrides.

```python
from sqlmodel import Field, SQLModel

# Good
class Session(SQLModel, table=True):
    id: str = Field(primary_key=True)
    project_id: str
    created_at: int

# Bad
class Session(SQLModel, table=True):
    id: str = Field(primary_key=True, sa_column_name="id")
    projectID: str = Field(sa_column_name="project_id")
    createdAt: int = Field(sa_column_name="created_at")

```

## Testing

* Avoid mocks as much as possible; favor integration or fixture-based testing.
* Test actual implementation, do not duplicate logic into tests.