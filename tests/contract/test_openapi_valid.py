from pathlib import Path

import yaml


REQUIRED_PATHS: dict[str, set[str]] = {
    "/v1/path": {"get"},
    "/v1/skill": {"get"},
    "/v1/session": {"get", "post"},
    "/v1/session/{id}": {"get", "patch"},
    "/v1/session/{id}/message": {"get", "post"},
    "/v1/session/{id}/interrupt": {"post"},
    "/v1/session/{id}/compact": {"post"},
    "/v1/session/{id}/message:delete": {"post"},
    "/v1/session/{id}/message:restore": {"post"},
    "/v1/provider": {"get"},
    "/v1/provider/{id}/model": {"get"},
    "/v1/provider/connect": {"post"},
    "/v1/agent": {"get"},
    "/v1/permission": {"get"},
    "/v1/permission/{id}/reply": {"post"},
    "/v1/question": {"get"},
    "/v1/question/{id}/reply": {"post"},
    "/v1/question/{id}/reject": {"post"},
    "/v1/event": {"get"},
}


def test_openapi_v1_contract_has_required_paths_and_schemas() -> None:
    spec_path = Path("openapi/hotaru.v1.yaml")
    assert spec_path.exists(), "openapi/hotaru.v1.yaml must exist"

    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))

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

    error_props = schemas["ErrorResponse"]["properties"]["error"]["properties"]
    assert "code" in error_props
    assert "message" in error_props
    assert "details" in error_props

    sse = schemas["SseEnvelope"]
    assert {"type", "data", "timestamp"}.issubset(set(sse["properties"].keys()))
    assert set(sse.get("required", [])) == {"type", "data", "timestamp"}
