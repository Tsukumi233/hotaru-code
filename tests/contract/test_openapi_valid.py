from hotaru.server.server import Server


REQUIRED_PATHS: dict[str, set[str]] = {
    "/v1/path": {"get"},
    "/v1/skill": {"get"},
    "/v1/sessions": {"get", "post"},
    "/v1/sessions/{session_id}": {"get", "patch", "delete"},
    "/v1/sessions/{session_id}/messages": {"get", "post", "delete"},
    "/v1/sessions/{session_id}/interrupt": {"post"},
    "/v1/sessions/{session_id}/compact": {"post"},
    "/v1/sessions/{session_id}/messages/restore": {"post"},
    "/v1/providers": {"get"},
    "/v1/providers/{provider_id}/models": {"get"},
    "/v1/providers/connect": {"post"},
    "/v1/agents": {"get"},
    "/v1/preferences/current": {"get", "patch"},
    "/v1/permissions": {"get"},
    "/v1/permissions/{request_id}/reply": {"post"},
    "/v1/questions": {"get"},
    "/v1/questions/{request_id}/reply": {"post"},
    "/v1/questions/{request_id}/reject": {"post"},
    "/v1/events": {"get"},
    "/v1/ptys": {"get", "post"},
    "/v1/ptys/{pty_id}": {"get", "put", "delete"},
}


def test_openapi_v1_contract_has_required_paths_and_schemas() -> None:
    spec = Server._create_app().openapi()

    assert spec.get("openapi") == "3.1.0"

    paths = spec.get("paths", {})
    for path, methods in REQUIRED_PATHS.items():
        assert path in paths, f"missing required path: {path}"
        present = {m.lower() for m in paths[path].keys()}
        for method in methods:
            assert method in present, f"missing {method.upper()} on {path}"

    schemas = spec.get("components", {}).get("schemas", {})
    assert "ErrorResponse" in schemas
    assert "SseEnvelope" in schemas

    error = schemas["ErrorResponse"]["properties"]["error"]
    if "$ref" in error:
        key = str(error["$ref"]).rsplit("/", 1)[-1]
        error = schemas[key]
    error_props = error["properties"]
    assert "code" in error_props
    assert "message" in error_props
    assert "details" in error_props

    sse = schemas["SseEnvelope"]
    assert {"type", "data", "timestamp"}.issubset(set(sse["properties"].keys()))
    assert set(sse.get("required", [])) == {"type", "data", "timestamp"}

    event_get = paths["/v1/events"]["get"]
    params = event_get.get("parameters", [])
    parameter_components = spec.get("components", {}).get("parameters", {})
    names: set[str | None] = set()
    for item in params:
        if not isinstance(item, dict):
            continue
        ref = item.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/parameters/"):
            key = ref.rsplit("/", 1)[-1]
            component = parameter_components.get(key, {})
            if isinstance(component, dict):
                names.add(component.get("name"))
            continue
        names.add(item.get("name"))
    assert "session_id" in names
