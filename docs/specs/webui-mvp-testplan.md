# Hotaru WebUI MVP Test Plan

## Contract
- `tests/contract/test_openapi_valid.py`
  - `/v1/events` exposes `session_id` query parameter
  - SSE envelope schema remains present

## Server Integration
- `tests/server/test_event_stream_filtering.py`
  - session filter keeps matching events only
  - no filter returns full stream
- `tests/server/test_web_static_routes.py`
  - `/` serves index
  - `/web/<asset>` serves static asset
  - unknown `/web/*` falls back to SPA index
  - `/healthz/web` readiness status reflects dist availability

## CLI
- `tests/cli/test_web_command.py`
  - `hotaru web` delegates CLI options correctly
  - runtime serve function starts and stops server lifecycle

## Existing Regression Surface
- `tests/tui/test_api_client_contract.py`
- `tests/server/test_v1_routes.py`
- `tests/contract/test_openapi_valid.py`

Run baseline:

```bash
uv run pytest tests/contract tests/server tests/cli -q
```
