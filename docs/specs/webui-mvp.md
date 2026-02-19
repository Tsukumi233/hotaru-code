# Hotaru WebUI MVP Spec

## Goal
Deliver a browser UI that reuses existing `/v1` APIs and provides session/message streaming parity with the current TUI for single-user local usage.

## In Scope
- Session list and create flow (`/v1/session`)
- Session message history (`/v1/session/{id}/message`)
- Send message and interrupt (`/v1/session/{id}/message`, `/interrupt`)
- Runtime event stream via SSE (`/v1/event`)
- Pending permission/question list and reply actions
- Provider/agent selection before sending
- New CLI entrypoint: `hotaru web`

## Out of Scope
- Multi-user authentication and remote tenancy
- Full TUI feature parity (command palette, advanced dialogs, full transcript tooling)
- Frontend build pipeline integration into Python package release process

## Runtime Contract
- Web client consumes REST for initial state and mutation.
- Web client consumes SSE for incremental runtime updates.
- Server supports optional `session_id` query filter on `/v1/event`.
- SSE envelopes keep current shape: `{type, data, timestamp, session_id?}`.

## Error Handling
- REST errors are surfaced as request failures with response payload text.
- SSE parse errors are ignored per event.
- SSE disconnect sets UI status to `reconnecting`; browser auto-retry handles recovery.

## Default Assumptions
- Default project id is `default`.
- Web server binds `127.0.0.1:4096` unless overridden by CLI options.
- No auth added in this phase.
