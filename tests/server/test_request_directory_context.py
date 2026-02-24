from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from starlette.testclient import TestClient

from hotaru.project import Instance
from hotaru.server.server import Server


def test_request_directory_prefers_header_over_query(monkeypatch, app_ctx) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, str] = {}

    async def fake_create(cls, payload: dict, cwd: str, **_kw):
        captured["cwd"] = cwd
        return {"id": "ses_1", "project_id": payload.get("project_id", "proj_1")}

    monkeypatch.setattr("hotaru.app_services.session_service.SessionService.create", classmethod(fake_create))

    app = Server._create_app(app_ctx)
    with TestClient(app) as client:
        response = client.post(
            "/v1/sessions",
            params={"directory": "/query/path"},
            headers={"x-hotaru-directory": "/header/path"},
            json={"project_id": "proj_1"},
        )

    assert response.status_code == 200
    assert captured["cwd"] == "/header/path"


def test_request_directory_uses_query_when_header_missing(monkeypatch, app_ctx) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, str] = {}

    async def fake_message(cls, session_id: str, payload: dict, cwd: str, **_kwargs):
        captured["cwd"] = cwd
        return {"ok": True, "assistant_message_id": session_id, "status": "stop", "error": None}

    monkeypatch.setattr("hotaru.app_services.session_service.SessionService.message", classmethod(fake_message))

    app = Server._create_app(app_ctx)
    with TestClient(app) as client:
        response = client.post(
            "/v1/sessions/ses_1/messages",
            params={"directory": "/query/path"},
            json={"content": "hello"},
        )
        assert response.status_code == 200

    assert captured["cwd"] == "/query/path"


def test_request_directory_falls_back_to_process_cwd(monkeypatch, app_ctx) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, str] = {}

    async def fake_compact(cls, session_id: str, payload: dict, cwd: str, **_kwargs):
        captured["cwd"] = cwd
        return {"ok": True, "id": session_id}

    monkeypatch.setattr("hotaru.app_services.session_service.SessionService.compact", classmethod(fake_compact))

    app = Server._create_app(app_ctx)
    with TestClient(app) as client:
        response = client.post("/v1/sessions/ses_1/compact", json={"auto": True})

    assert response.status_code == 200
    assert captured["cwd"] == str(Path.cwd())


def test_request_directory_decodes_percent_encoded_header(monkeypatch, app_ctx) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, str] = {}
    encoded = quote("/tmp/热")

    async def fake_create(cls, payload: dict, cwd: str, **_kw):
        captured["cwd"] = cwd
        return {"id": "ses_1", "project_id": payload.get("project_id", "proj_1")}

    monkeypatch.setattr("hotaru.app_services.session_service.SessionService.create", classmethod(fake_create))

    app = Server._create_app(app_ctx)
    with TestClient(app) as client:
        response = client.post(
            "/v1/sessions",
            headers={"x-hotaru-directory": encoded},
            json={"project_id": "proj_1"},
        )

    assert response.status_code == 200
    assert captured["cwd"] == "/tmp/热"


def test_get_paths_reports_request_directory(monkeypatch, app_ctx) -> None:  # type: ignore[no-untyped-def]
    app = Server._create_app(app_ctx)
    with TestClient(app) as client:
        response = client.get(
            "/v1/path",
            headers={"x-hotaru-directory": "/workspace/one"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["cwd"] == "/workspace/one"


def test_list_sessions_uses_resolved_directory(monkeypatch, app_ctx) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, str | None] = {}

    async def fake_list(cls, project_id: str | None, cwd: str):
        captured["project_id"] = project_id
        captured["cwd"] = cwd
        return []

    monkeypatch.setattr("hotaru.app_services.session_service.SessionService.list", classmethod(fake_list))

    app = Server._create_app(app_ctx)
    with TestClient(app) as client:
        response = client.get(
            "/v1/sessions",
            headers={"x-hotaru-directory": "/workspace/two"},
        )

    assert response.status_code == 200
    assert captured["project_id"] is None
    assert captured["cwd"] == "/workspace/two"


def test_request_directory_binds_instance_context(monkeypatch, app_ctx) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, str] = {}

    async def fake_create(cls, payload: dict, cwd: str, **_kw):
        captured["cwd"] = cwd
        captured["instance_directory"] = Instance.directory()
        return {"id": "ses_1", "project_id": payload.get("project_id", "proj_1")}

    monkeypatch.setattr("hotaru.app_services.session_service.SessionService.create", classmethod(fake_create))

    app = Server._create_app(app_ctx)
    with TestClient(app) as client:
        response = client.post(
            "/v1/sessions",
            headers={"x-hotaru-directory": "/workspace/scoped"},
            json={"project_id": "proj_1"},
        )

    assert response.status_code == 200
    assert captured["cwd"] == "/workspace/scoped"
    assert captured["instance_directory"] == "/workspace/scoped"


def test_instance_bootstrap_runs_once_per_directory(monkeypatch, app_ctx) -> None:  # type: ignore[no-untyped-def]
    calls: dict[str, int] = {}
    first = "/workspace/bootstrap-one"
    second = "/workspace/bootstrap-two"

    async def fake_bootstrap(*, app):
        directory = Instance.directory()
        calls[directory] = calls.get(directory, 0) + 1

    monkeypatch.setattr("hotaru.server.app.instance_bootstrap", fake_bootstrap)

    app = Server._create_app(app_ctx)
    with TestClient(app) as client:
        response_one = client.get("/v1/path", headers={"x-hotaru-directory": first})
        response_two = client.get("/v1/path", headers={"x-hotaru-directory": first})
        response_three = client.get("/v1/path", headers={"x-hotaru-directory": second})

    assert response_one.status_code == 200
    assert response_two.status_code == 200
    assert response_three.status_code == 200
    assert calls == {
        first: 1,
        second: 1,
    }
