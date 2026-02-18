# Repository Guidelines

## Project Structure & Module Organization
- This repo is a python translation of the OpenCode project(at ../opencode).
- This is not a toy project; it is intended to be a production-quality codebase for a real-world agent framework.
- Core package code lives under `src/hotaru/` with domain modules such as `cli/`, `tui/`, `session/`, `tool/`, `provider/`, and `mcp/`.
- CLI entrypoint is `src/hotaru/cli/main.py`; packaged command is `hotaru`.
- Keep tests in `tests/`. Mirror package paths when possible.
- Runtime/project config is in `hotaru.json`.

## Build, Test, and Development Commands
- `uv sync` - install/update dependencies from `pyproject.toml` and `uv.lock`.
- `uv run hotaru` - launch the default TUI.
- `uv run hotaru run -p "your prompt"` - execute a one-shot prompt.
- `uv run pytest tests` - run tests (use as tests are added).

## Coding Style & Naming Conventions
- Follow modern software engineering practices with an emphasis on readability, maintainability, and modularity.
- Keep minimal technical debt. If there's breaking changes or refactors, no need to preserve API or compatibility; prioritize clean implementations.
- Target Python 3.12+, use 4-space indentation, type hints, and `async`/`await` for I/O paths.
- Follow existing naming: `snake_case` for modules/functions, `PascalCase` for classes, `UPPER_SNAKE_CASE` for constants.
- Architecture & debugging discipline (no “shitsnowball” patches):
  - Any bugfix/refactor must prioritize root-cause fixes over symptom patches.
  - Do not add ad-hoc conditionals in upper layers (`session/`, `tui/`, `cli/`, generic core flow) for lower-layer quirks.
  - Keep maximum loose coupling: one responsibility per layer, stable interfaces, dependency inversion where applicable.
  - New compatibility logic must live at boundaries (`src/hotaru/provider/`, adapters, transforms, SDK wrappers), driven by capability/config, not scattered `if/else`.
  - If a fix requires cross-layer hacks, stop and refactor ownership boundaries first, then implement the fix.
  - NO HARD CODED CONFIG/MAGIC STRINGS.

## Testing Guidelines
- There is no formal coverage gate yet; include meaningful coverage for all changed code paths.

## Commit Message Guidelines
- We use release-please-action for automated semantic versioning and changelog generation. Follow the Conventional Commits format.
- Do not mention OpenCode in commit messages.

## Security & Configuration Tips
- Never commit API keys or tokens.
- Treat `hotaru.json` as local/developer configuration and sanitize provider details before sharing.
