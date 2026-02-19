from pathlib import Path

from starlette.testclient import TestClient

from hotaru.server.server import Server


def _write_web_dist(root: Path) -> None:
    (root / "assets").mkdir(parents=True, exist_ok=True)
    (root / "index.html").write_text("<!doctype html><html><body>hotaru-web</body></html>", encoding="utf-8")
    (root / "assets" / "app.js").write_text("console.log('ok');", encoding="utf-8")


def test_root_serves_web_index(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    dist = tmp_path / "dist"
    _write_web_dist(dist)
    monkeypatch.setenv("HOTARU_WEB_DIST", str(dist))

    app = Server._create_app()
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "hotaru-web" in response.text


def test_web_path_serves_asset_or_spa_fallback(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    dist = tmp_path / "dist"
    _write_web_dist(dist)
    monkeypatch.setenv("HOTARU_WEB_DIST", str(dist))

    app = Server._create_app()
    with TestClient(app) as client:
        asset = client.get("/web/assets/app.js")
        assert asset.status_code == 200
        assert "console.log('ok');" in asset.text

        root_asset = client.get("/assets/app.js")
        assert root_asset.status_code == 200
        assert "console.log('ok');" in root_asset.text

        fallback = client.get("/web/session/session_1")
        assert fallback.status_code == 200
        assert "hotaru-web" in fallback.text


def test_web_health_reports_readiness(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    dist = tmp_path / "dist"
    _write_web_dist(dist)
    monkeypatch.setenv("HOTARU_WEB_DIST", str(dist))

    app = Server._create_app()
    with TestClient(app) as client:
        response = client.get("/healthz/web")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "web": {"ready": True}}
