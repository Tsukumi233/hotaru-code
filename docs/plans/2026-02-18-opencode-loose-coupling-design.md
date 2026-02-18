# Hotaru OpenCode-Level Loose Coupling Design

## Metadata
- Date: 2026-02-18
- Scope: Align to OpenCode-level modular loose coupling with contract-first architecture
- Decision: One-shot migration, contract-first, OpenAPI 3.1 + typed Python client, in-process ASGI server for TUI

## Goal
Make TUI interact with backend strictly through API contracts, remove direct UI-to-domain coupling, and centralize use-case orchestration into an application service layer.

## Confirmed Constraints
1. One-shot switch in a single PR; remove old direct-coupling paths in the same change.
2. Contract-first: OpenAPI 3.1 as single source of truth.
3. Typed Python client generated from OpenAPI.
4. Runtime topology: TUI starts embedded in-process ASGI server and calls via HTTP client transport.

## Target Architecture
### Layering
1. Interface layer
- `src/hotaru/tui/*`: UI, view-model state, typed client calls only
- `src/hotaru/server/*`: thin HTTP routes and SSE transport only

2. Application layer
- `src/hotaru/app_services/*`: use-case orchestration
- Owns workflows such as session creation, prompt streaming, provider onboarding, compaction, permission/question replies

3. Domain layer
- Existing `session/provider/agent/tool/permission/question/mcp` modules
- No direct dependencies from TUI after migration

4. Contract layer
- `openapi/hotaru.v1.yaml`
- Generated typed client under `src/hotaru/api_client/`

## API Contract Baseline
Versioned route namespace: `/v1/*`

Required endpoints:
- `POST /v1/session`
- `GET /v1/session`
- `GET /v1/session/{id}`
- `POST /v1/session/{id}/message:stream`
- `POST /v1/session/{id}/compact`
- `GET /v1/provider`
- `GET /v1/provider/{id}/model`
- `POST /v1/provider/connect`
- `GET /v1/agent`
- `GET /v1/permission`
- `POST /v1/permission/{id}/reply`
- `GET /v1/question`
- `POST /v1/question/{id}/reply`
- `POST /v1/question/{id}/reject`
- `GET /v1/event`

Standard error payload:
- `ErrorResponse.error.code`
- `ErrorResponse.error.message`
- `ErrorResponse.error.details` (optional)

Unified SSE envelope:
- `{ type, data, timestamp, session_id? }`

## Module Refactoring Plan
### New modules
- `src/hotaru/app_services/session_service.py`
- `src/hotaru/app_services/provider_service.py`
- `src/hotaru/app_services/permission_service.py`
- `src/hotaru/app_services/question_service.py`
- `src/hotaru/app_services/event_service.py`
- `openapi/hotaru.v1.yaml`
- `src/hotaru/api_client/` (generated)

### Existing modules to refactor
- `src/hotaru/server/server.py`: routes become transport-only and delegate to app services
- `src/hotaru/tui/context/sdk.py`: migrate to typed client; remove direct domain orchestration calls
- `src/hotaru/tui/app.py`: provider onboarding through `/v1/provider/connect`

## Data Flow
1. TUI bootstraps embedded ASGI app.
2. Typed client uses ASGI-backed HTTP transport.
3. TUI sends message through `POST /v1/session/{id}/message:stream`.
4. Server route delegates to session app service.
5. App service orchestrates domain modules and streams normalized SSE events.
6. TUI consumes contract-defined envelopes and updates UI state.

## Error Handling and Stability
- All route exceptions mapped to contract error codes.
- Stream failures emitted as normalized `type="error"` SSE events with contract payload.
- TUI handles errors by code only, not parsing exception strings.

## Test Strategy
1. Contract tests
- OpenAPI schema parse/validate
- required path/operation presence checks

2. Server route tests
- request/response shape tests against contract
- SSE envelope/event-order tests for streaming endpoints

3. App service tests
- session stream orchestration happy path and failures
- provider connect validation/auth/config integration
- compact flow behavior

4. TUI boundary tests
- `SDKContext` tests use typed client mocks only
- no monkeypatching domain modules from TUI tests

5. End-to-end tests
- embedded server + typed client + TUI session flow

## Acceptance Criteria
1. No direct imports from TUI into domain orchestration classes (`SessionPrompt`, `SystemPrompt`, `ProviderAuth`, `ConfigManager`, `Provider`, `Agent`, `Session`).
2. TUI domain interactions exclusively via generated typed client and `/v1/*` endpoints.
3. Server routes are thin; orchestration resides in `app_services`.
4. SSE and error payloads conform to contract.
5. Full test suite passes.

## Out of Scope
- New standalone desktop/web UI implementation
- Non-essential visual UX redesign

