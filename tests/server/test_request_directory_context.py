from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from starlette.testclient import TestClient

from hotaru.server.server import Server


def test_request_directory_prefers_header_over_query(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, str] = {}

    async def fake_create(cls, payload: dict, cwd: str):
        captured["cwd"] = cwd
        return {"id": "ses_1", "project_id": payload.get("project_id", "proj_1")}

    monkeypatch.setattr("hotaru.app_services.session_service.SessionService.create", classmethod(fake_create))

    app = Server._create_app()
    with TestClient(app) as client:
        response = client.post(
            "/v1/session",
            params={"directory": "/query/path"},
            headers={"x-hotaru-directory": "/header/path"},
            json={"project_id": "proj_1"},
        )

    assert response.status_code == 200
    assert captured["cwd"] == "/header/path"


def test_request_directory_uses_query_when_header_missing(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, str] = {}

    async def fake_message(cls, session_id: str, payload: dict, cwd: str):
        captured["cwd"] = cwd
        return {"ok": True, "assistant_message_id": session_id, "status": "stop", "error": None}

    monkeypatch.setattr("hotaru.app_services.session_service.SessionService.message", classmethod(fake_message))

    app = Server._create_app()
    with TestClient(app) as client:
        response = client.post(
            "/v1/session/ses_1/message",
            params={"directory": "/query/path"},
            json={"content": "hello"},
        )
        assert response.status_code == 200

    assert captured["cwd"] == "/query/path"


def test_request_directory_falls_back_to_process_cwd(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, str] = {}

    async def fake_compact(cls, session_id: str, payload: dict, cwd: str):
        captured["cwd"] = cwd
        return {"ok": True, "id": session_id}

    monkeypatch.setattr("hotaru.app_services.session_service.SessionService.compact", classmethod(fake_compact))

    app = Server._create_app()
    with TestClient(app) as client:
        response = client.post("/v1/session/ses_1/compact", json={"auto": True})

    assert response.status_code == 200
    assert captured["cwd"] == str(Path.cwd())


def test_request_directory_decodes_percent_encoded_header(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, str] = {}
    encoded = quote("/tmp/热")

    async def fake_create(cls, payload: dict, cwd: str):
        captured["cwd"] = cwd
        return {"id": "ses_1", "project_id": payload.get("project_id", "proj_1")}

    monkeypatch.setattr("hotaru.app_services.session_service.SessionService.create", classmethod(fake_create))

    app = Server._create_app()
    with TestClient(app) as client:
        response = client.post(
            "/v1/session",
            headers={"x-hotaru-directory": encoded},
            json={"project_id": "proj_1"},
        )

    assert response.status_code == 200
    assert captured["cwd"] == "/tmp/热"


def test_get_paths_reports_request_directory(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    app = Server._create_app()
    with TestClient(app) as client:
        response = client.get(
            "/v1/path",
            headers={"x-hotaru-directory": "/workspace/one"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["cwd"] == "/workspace/one"
