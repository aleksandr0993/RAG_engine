from __future__ import annotations

from fastapi.testclient import TestClient


def test_cors_disabled_no_expose_headers(client):
    r = client.get("/api/v1/projects", headers={"Origin": "http://localhost:3000"})
    assert r.status_code == 200
    assert r.headers.get("access-control-expose-headers") is None


def test_cors_exposes_pagination_headers(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'cors.db'}")
    monkeypatch.setenv("FILES_ROOT", str(data_dir / "files"))
    monkeypatch.setenv("EXPORTS_ROOT", str(data_dir / "exports"))
    monkeypatch.setenv("ENABLE_NOTEBOOK_EXECUTION", "false")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://app.local:3000")

    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    with TestClient(app) as tc:
        r = tc.get("/api/v1/projects", headers={"Origin": "http://app.local:3000"})
    assert r.status_code == 200
    expose = (r.headers.get("access-control-expose-headers") or "").lower()
    assert "x-total-count" in expose
    assert "x-next-cursor" in expose
    assert "x-total-count-truncated" in expose
