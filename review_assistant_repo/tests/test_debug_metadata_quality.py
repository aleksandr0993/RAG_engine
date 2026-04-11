"""HTTP debug routes for iteration metadata audit/backfill."""

from __future__ import annotations


def test_debug_metadata_quality_audit(client):
    r = client.get("/api/v1/debug/metadata_quality_audit", params={"sample_limit": 5})
    assert r.status_code == 200
    data = r.json()
    assert data["projects_sample_size"] <= 5
    assert "iteration_fix_summary_invalid_type" in data


def test_debug_metadata_backfill(client):
    r = client.post(
        "/api/v1/debug/metadata_backfill",
        params={"project_limit": 10, "resolution_limit": 10},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["projects_scanned"] <= 10
    assert data["resolutions_scanned"] <= 10
    assert "projects_updated" in data
    assert "resolutions_updated" in data
