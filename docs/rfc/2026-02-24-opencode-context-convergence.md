# RFC: Opencode-style Context Convergence (Backend Main Path)

## Status
- Implemented (backend main path)
- Author: codex
- Date: 2026-02-24

## Motivation
Hotaru currently exposes runtime scope through multiple overlapping paths:

1. explicit `AppContext` dependency passing
2. `Bus` context binding via `ContextVar`
3. FastAPI `app.state.ctx` + dependency resolution
4. ad-hoc `Instance.provide(...)` fallback in session internals

This increases cognitive load and makes runtime scope harder to reason about.

## Goals
1. Align request execution with opencode's instance-first model.
2. Ensure `/v1/*` requests run inside a project `Instance` context.
3. Keep external HTTP API and SSE contract unchanged.
4. Reduce duplicated context-binding logic inside session stack.

## Non-goals
1. No breaking changes for `/v1/*` route schemas.
2. No TUI context architecture rewrite in this phase.
3. No app-level runtime decomposition (`AppContext` split) in this phase.

## Proposed Design
### 1) Server request scoping
For `/v1/*` requests, server middleware will:

1. resolve request directory once
2. bind request bus scope
3. execute handler under `Instance.provide(directory=...)`

This mirrors opencode's "middleware enters instance scope before routing" pattern.

### 2) Shared instance-scope helper
Introduce a single helper (`run_in_instance`) that:

1. reuses current instance scope when directory already matches
2. enters `Instance.provide` when scope is missing or mismatched

All session-level fallback paths use this helper rather than duplicating context checks.

## Compatibility
### External
- No HTTP contract changes.
- No route path changes.
- No SSE envelope changes.

### Internal
- Session context fallback logic is centralized in one helper module.
- Server dependencies can read a cached request directory from middleware state.
- Runtime resolution now comes from instance scope (`use_runtime`) instead of `app.state`.

## Rollout Plan
1. Add `run_in_instance` helper.
2. Switch `/v1/*` server middleware to instance-scoped execution.
3. Add `instance_bootstrap` and bind `AppContext` into instance scope.
4. Migrate `SessionPrompt.prompt` and `SessionProcessor.process` to helper.
5. Add regression tests for request-to-instance directory propagation and bootstrap behavior.
6. Run focused server/session tests and then full suite.

## Risks
1. Requests now initialize project instance context more consistently, increasing per-request scope setup cost.
2. Tests that assumed no instance scope in server paths may require updates.

## Success Criteria
1. `/v1/*` handler execution observes `Instance.directory()` matching resolved request directory.
2. Existing API contract tests stay green.
3. Session processor/prompting no longer duplicate instance-mismatch checks.

## Implemented Changes
1. Added `run_in_instance` helper and migrated session entry points to it.
2. Switched `/v1/*` request execution to instance-scoped middleware flow.
3. Added `instance_bootstrap` + `runtime_scope` binding (`bind_runtime` / `use_runtime`).
4. Removed `app.state.ctx` dependency from app-context resolution path.
5. Added instance/state runtime reset helpers for deterministic teardown in tests.
6. Added/updated server regression tests for instance binding and bootstrap behavior.
