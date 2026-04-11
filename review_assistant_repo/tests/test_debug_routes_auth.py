"""Optional JWT gate for /debug/* and /projects/*/debug/* (REQUIRE_AUTH_FOR_DEBUG_ROUTES)."""

from __future__ import annotations

import jwt
import pytest


@pytest.fixture()
def client_debug_auth_on(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test_debug_auth.db'}")
    monkeypatch.setenv("FILES_ROOT", str(data_dir / "files"))
    monkeypatch.setenv("EXPORTS_ROOT", str(data_dir / "exports"))
    monkeypatch.setenv("ENABLE_NOTEBOOK_EXECUTION", "false")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "unit-test-debug-routes-secret")
    monkeypatch.setenv("REQUIRE_AUTH_FOR_DEBUG_ROUTES", "true")

    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client


def _debug_bearer() -> str:
    return jwt.encode(
        {"sub": "debug-test-user", "aud": "authenticated"},
        "unit-test-debug-routes-secret",
        algorithm="HS256",
    )


@pytest.mark.parametrize(
    "method,path,kwargs",
    [
        ("GET", "/api/v1/debug/capture_metrics", {}),
        ("GET", "/api/v1/debug/review_metrics", {}),
        ("GET", "/api/v1/debug/practicum_stats", {"params": {"limit": 2}}),
        ("GET", "/api/v1/debug/metadata_quality_audit", {"params": {"sample_limit": 2}}),
        ("POST", "/api/v1/debug/metadata_backfill", {"params": {"project_limit": 2, "resolution_limit": 2}}),
    ],
)
def test_debug_routes_require_auth_when_flag_on(client_debug_auth_on, method, path, kwargs):
    r = client_debug_auth_on.request(method, path, **kwargs)
    assert r.status_code == 401

    headers = {"Authorization": f"Bearer {_debug_bearer()}"}
    r2 = client_debug_auth_on.request(method, path, headers=headers, **kwargs)
    assert r2.status_code == 200


def test_project_scoped_debug_requires_auth(client_debug_auth_on):
    r = client_debug_auth_on.get("/api/v1/projects/nope/debug/review_timeline")
    assert r.status_code == 401

    headers = {"Authorization": f"Bearer {_debug_bearer()}"}
    r2 = client_debug_auth_on.get("/api/v1/projects/nope/debug/review_timeline", headers=headers)
    assert r2.status_code == 404
