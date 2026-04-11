from pathlib import Path

import pytest

from app.capture.datalens import _validate_capture_url
from app.db import get_session_local
from app.models import Project


def test_validate_capture_url_rejects_non_datalens_host(monkeypatch):
    monkeypatch.setenv("DATALENS_URL_ALLOWLIST_ENABLED", "true")
    from app.config import get_settings

    get_settings.cache_clear()
    with pytest.raises(ValueError, match="allowlist"):
        _validate_capture_url("https://example.com/evil")


def test_validate_capture_url_rejects_http_scheme(monkeypatch):
    monkeypatch.setenv("DATALENS_URL_ALLOWLIST_ENABLED", "true")
    from app.config import get_settings

    get_settings.cache_clear()
    with pytest.raises(ValueError, match="scheme"):
        _validate_capture_url("http://datalens.yandex/x")


def test_upload_rejects_path_traversal_criteria_map(client):
    sample_path = Path("examples/sample_query.sql")
    with sample_path.open("rb") as f:
        response = client.post(
            "/api/v1/projects/upload",
            files={"file": ("sample_query.sql", f, "text/plain")},
            data={"criteria_map_code": "../style_profiles/alex_review_v1"},
        )
    assert response.status_code == 400
    assert "Unknown criteria map" in response.json()["detail"]


def test_upload_rejects_oversized_file(client_small_upload):
    response = client_small_upload.post(
        "/api/v1/projects/upload",
        files={"file": ("big.sql", b"x" * 50, "text/plain")},
    )
    assert response.status_code == 413


def test_get_unknown_project_returns_404(client):
    r = client.get("/api/v1/projects/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


def test_review_marks_failed_when_original_missing(client):
    sample_path = Path("examples/sample_query.sql")
    with sample_path.open("rb") as f:
        up = client.post(
            "/api/v1/projects/upload",
            files={"file": ("sample_query.sql", f, "text/plain")},
        )
    assert up.status_code == 200
    project_id = up.json()["project_id"]

    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        proj = db.get(Project, project_id)
        assert proj is not None
        orig = next(f for f in proj.files if f.kind == "original")
        p = Path(orig.storage_path)
        assert p.is_file()
        p.unlink()
    finally:
        db.close()

    rev = client.post(f"/api/v1/projects/{project_id}/review")
    assert rev.status_code == 500

    st = client.get(f"/api/v1/projects/{project_id}")
    assert st.json()["status"] == "failed"
