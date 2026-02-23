from starlette.testclient import TestClient

from hotaru.server.server import Server


def test_missing_session_stays_not_found(monkeypatch, app_ctx) -> None:  # type: ignore[no-untyped-def]
    async def fake_get(cls, session_id: str):
        return None

    monkeypatch.setattr("hotaru.app_services.session_service.SessionService.get", classmethod(fake_get))

    app = Server._create_app(app_ctx)
    with TestClient(app) as client:
        response = client.get("/v1/sessions/ses_missing")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_key_error_is_not_mapped_to_not_found(monkeypatch, app_ctx) -> None:  # type: ignore[no-untyped-def]
    async def fake_list(cls, project_id: str | None, cwd: str):
        raise KeyError("unexpected-key")

    monkeypatch.setattr("hotaru.app_services.session_service.SessionService.list", classmethod(fake_list))

    app = Server._create_app(app_ctx)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/v1/sessions")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
