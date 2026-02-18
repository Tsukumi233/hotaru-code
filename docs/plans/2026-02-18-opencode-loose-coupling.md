# OpenCode-Level Loose Coupling Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** One-shot migrate Hotaru TUI to a contract-first API boundary (OpenAPI 3.1 + typed client) with in-process ASGI server, removing direct TUI-to-domain coupling.

**Architecture:** Introduce `app_services` as orchestration boundary, define `/v1/*` contract in OpenAPI, make server routes transport-only, and make TUI SDK context call only generated typed client over ASGI transport. Remove legacy direct domain paths in the same PR.

**Tech Stack:** Python 3.12, Starlette, Pydantic, SSE, OpenAPI 3.1, pytest, httpx ASGI transport.

---

### Task 1: Create API Contract Skeleton

**Files:**
- Create: `openapi/hotaru.v1.yaml`
- Test: `tests/contract/test_openapi_valid.py`

**Step 1: Write the failing test**
- Add assertions for OpenAPI version (`3.1.0`) and required `/v1/*` paths.

**Step 2: Run test to verify it fails**
- Run: `uv run pytest tests/contract/test_openapi_valid.py -q`
- Expected: FAIL (file/paths missing).

**Step 3: Write minimal implementation**
- Create OpenAPI file with info block, server block, and required path stubs + schemas (`ErrorResponse`, `SseEnvelope`).

**Step 4: Run test to verify it passes**
- Run: `uv run pytest tests/contract/test_openapi_valid.py -q`
- Expected: PASS.

**Step 5: Commit**
- `git add openapi/hotaru.v1.yaml tests/contract/test_openapi_valid.py`
- `git commit -m "feat(contract): add v1 openapi skeleton"`

### Task 2: Introduce Application Service Layer

**Files:**
- Create: `src/hotaru/app_services/__init__.py`
- Create: `src/hotaru/app_services/session_service.py`
- Create: `src/hotaru/app_services/provider_service.py`
- Create: `src/hotaru/app_services/permission_service.py`
- Create: `src/hotaru/app_services/question_service.py`
- Create: `src/hotaru/app_services/event_service.py`
- Test: `tests/server/test_app_services.py`

**Step 1: Write the failing test**
- Assert services expose methods for session create/list/get, stream prompt, compact, provider connect, permission/question replies.

**Step 2: Run test to verify it fails**
- Run: `uv run pytest tests/server/test_app_services.py -q`
- Expected: FAIL (module/functions missing).

**Step 3: Write minimal implementation**
- Implement thin service classes that delegate to existing domain modules.
- Keep logic centralized here; no server/tui logic.

**Step 4: Run test to verify it passes**
- Run: `uv run pytest tests/server/test_app_services.py -q`
- Expected: PASS.

**Step 5: Commit**
- `git add src/hotaru/app_services tests/server/test_app_services.py`
- `git commit -m "feat(app): add application service boundary"`

### Task 3: Refactor Server Routes to Thin Transport

**Files:**
- Modify: `src/hotaru/server/server.py`
- Test: `tests/server/test_v1_routes.py`
- Test: `tests/server/test_permission_question_routes.py`

**Step 1: Write the failing test**
- Add `/v1/*` route tests for status codes and response shapes.
- Add stream test for `/v1/session/{id}/message:stream` SSE envelope.

**Step 2: Run test to verify it fails**
- Run: `uv run pytest tests/server/test_v1_routes.py -q`
- Expected: FAIL (routes absent/shape mismatch).

**Step 3: Write minimal implementation**
- Add `/v1/*` routes.
- Map request->service->response only.
- Normalize error response and SSE envelope in one place.

**Step 4: Run test to verify it passes**
- Run: `uv run pytest tests/server/test_v1_routes.py tests/server/test_permission_question_routes.py -q`
- Expected: PASS.

**Step 5: Commit**
- `git add src/hotaru/server/server.py tests/server/test_v1_routes.py tests/server/test_permission_question_routes.py`
- `git commit -m "feat(server): add v1 transport routes over app services"`

### Task 4: Add Generated Typed API Client Integration Point

**Files:**
- Create: `src/hotaru/api_client/__init__.py`
- Create: `src/hotaru/api_client/client.py`
- Test: `tests/tui/test_api_client_contract.py`

**Step 1: Write the failing test**
- Validate typed client methods correspond to required `/v1/*` operations.

**Step 2: Run test to verify it fails**
- Run: `uv run pytest tests/tui/test_api_client_contract.py -q`
- Expected: FAIL.

**Step 3: Write minimal implementation**
- Add generated (or generation-output) typed client module and initialization helper.
- Ensure ASGI transport can be injected for in-process usage.

**Step 4: Run test to verify it passes**
- Run: `uv run pytest tests/tui/test_api_client_contract.py -q`
- Expected: PASS.

**Step 5: Commit**
- `git add src/hotaru/api_client tests/tui/test_api_client_contract.py`
- `git commit -m "feat(client): add typed v1 api client"`

### Task 5: Migrate TUI SDKContext to API Client Only

**Files:**
- Modify: `src/hotaru/tui/context/sdk.py`
- Test: `tests/tui/test_sdk_context_api_boundary.py`
- Modify: `tests/tui/test_sdk_context.py`

**Step 1: Write the failing test**
- Add tests that mock typed client methods, not domain modules.
- Assert send_message/session operations work through API client calls.

**Step 2: Run test to verify it fails**
- Run: `uv run pytest tests/tui/test_sdk_context_api_boundary.py -q`
- Expected: FAIL.

**Step 3: Write minimal implementation**
- Replace direct imports/usage of domain orchestration in SDKContext with typed client calls.
- Keep event adaptation limited to contract envelope mapping.

**Step 4: Run test to verify it passes**
- Run: `uv run pytest tests/tui/test_sdk_context_api_boundary.py tests/tui/test_sdk_context.py -q`
- Expected: PASS.

**Step 5: Commit**
- `git add src/hotaru/tui/context/sdk.py tests/tui/test_sdk_context_api_boundary.py tests/tui/test_sdk_context.py`
- `git commit -m "refactor(tui): use api client boundary in sdk context"`

### Task 6: Migrate TUI Provider Onboarding to API Endpoint

**Files:**
- Modify: `src/hotaru/tui/app.py`
- Modify: `src/hotaru/tui/context/sdk.py`
- Test: `tests/tui/test_provider_connect_via_api.py`

**Step 1: Write the failing test**
- Assert provider connect flow calls `/v1/provider/connect` via client and no direct `ConfigManager/ProviderAuth` interactions from TUI.

**Step 2: Run test to verify it fails**
- Run: `uv run pytest tests/tui/test_provider_connect_via_api.py -q`
- Expected: FAIL.

**Step 3: Write minimal implementation**
- Move onboarding orchestration into provider service route.
- TUI dialog flow only collects input and calls client.

**Step 4: Run test to verify it passes**
- Run: `uv run pytest tests/tui/test_provider_connect_via_api.py -q`
- Expected: PASS.

**Step 5: Commit**
- `git add src/hotaru/tui/app.py src/hotaru/tui/context/sdk.py tests/tui/test_provider_connect_via_api.py`
- `git commit -m "refactor(tui): route provider onboarding through v1 api"`

### Task 7: Remove Legacy Direct-Coupling Paths

**Files:**
- Modify: `src/hotaru/tui/context/sdk.py`
- Modify: `src/hotaru/tui/app.py`
- Test: `tests/tui/test_no_domain_imports.py`

**Step 1: Write the failing test**
- Add static import boundary test forbidding TUI imports of domain orchestration symbols.

**Step 2: Run test to verify it fails**
- Run: `uv run pytest tests/tui/test_no_domain_imports.py -q`
- Expected: FAIL.

**Step 3: Write minimal implementation**
- Delete old paths and imports.
- Keep only typed client boundary.

**Step 4: Run test to verify it passes**
- Run: `uv run pytest tests/tui/test_no_domain_imports.py -q`
- Expected: PASS.

**Step 5: Commit**
- `git add src/hotaru/tui/context/sdk.py src/hotaru/tui/app.py tests/tui/test_no_domain_imports.py`
- `git commit -m "refactor(tui): remove direct domain coupling paths"`

### Task 8: End-to-End Embedded Server Validation

**Files:**
- Create: `tests/tui/test_embedded_server_e2e.py`
- Modify: `src/hotaru/tui/context/sdk.py` (if needed)

**Step 1: Write the failing test**
- Add e2e test: initialize embedded ASGI server + typed client, create session, stream one prompt, observe normalized events.

**Step 2: Run test to verify it fails**
- Run: `uv run pytest tests/tui/test_embedded_server_e2e.py -q`
- Expected: FAIL.

**Step 3: Write minimal implementation**
- Add embedded transport wiring and lifecycle handling.

**Step 4: Run test to verify it passes**
- Run: `uv run pytest tests/tui/test_embedded_server_e2e.py -q`
- Expected: PASS.

**Step 5: Commit**
- `git add tests/tui/test_embedded_server_e2e.py src/hotaru/tui/context/sdk.py`
- `git commit -m "test(tui): add embedded server e2e coverage"`

### Task 9: Full Verification and Cleanup

**Files:**
- Modify as needed from previous tasks
- Test: full suite

**Step 1: Run focused suites**
- `uv run pytest tests/server tests/tui tests/cli -q`

**Step 2: Run full suite**
- `uv run pytest tests -q`

**Step 3: Verify acceptance checks**
- Confirm no forbidden imports in TUI.
- Confirm `/v1/*` endpoints operational.
- Confirm SSE/error envelope consistency.

**Step 4: Final cleanup commit**
- `git add -A`
- `git commit -m "refactor: align architecture to contract-first api boundary"`

