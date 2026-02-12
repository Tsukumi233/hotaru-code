# TUI Migration Map (Hotaru <- OpenCode)

## Goal
Track high-impact migration targets from `../opencode/packages/app/src` into `src/hotaru/tui` while keeping Textual-native architecture.

## Mapping
- `pages/session.tsx` -> `src/hotaru/tui/screens.py`
  - Session lifecycle, message timeline, prompt loop.
- `components/prompt-input.tsx` -> `src/hotaru/tui/widgets.py`
  - Slash completion, submission behavior, command affordances.
- `context/command.tsx` -> `src/hotaru/tui/commands.py` + `src/hotaru/tui/app.py`
  - Command registry, palette invocation, availability checks.
- `components/status-popover.tsx` -> `src/hotaru/tui/dialogs.py` (`StatusDialog`) + `src/hotaru/tui/app.py`
  - Runtime status (model/agent/MCP/LSP), refresh flow.

## Implemented in This Pass
- Session history loading for resumed sessions.
- Route-driven navigation for home/session entry points.
- Command execution unification and disabled-command reasons.
- Runtime status dialog and MCP/LSP refresh integration.
- Transcript copy/export/share command flows for the active session.

## Deferred
- Worktree/file-tree/review panels.
- Terminal tab system parity with OpenCode.
