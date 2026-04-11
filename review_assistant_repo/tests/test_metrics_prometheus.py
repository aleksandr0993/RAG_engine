"""Prometheus text metrics endpoint."""

from __future__ import annotations


def test_metrics_includes_iteration_resolution_series(client):
    r = client.get("/api/v1/metrics")
    assert r.status_code == 200
    text = r.text
    assert "# HELP review_assistant_projects" in text
    assert "# TYPE review_assistant_projects gauge" in text
    assert "# HELP review_assistant_iteration_issue_resolution_rows_total" in text
    assert "# TYPE review_assistant_iteration_issue_resolution_rows_total gauge" in text
    assert "review_assistant_iteration_issue_resolution_rows_total" in text
    assert "# HELP review_assistant_iteration_issue_resolutions" in text
    assert "# TYPE review_assistant_iteration_issue_resolutions gauge" in text
    assert "# HELP review_assistant_llm_circuit_open_total" in text
    assert "# TYPE review_assistant_llm_circuit_open_total counter" in text
    assert "# HELP review_assistant_metadata_quality_audit_projects_sample_size" in text
    assert "# TYPE review_assistant_metadata_quality_audit_projects_sample_size gauge" in text
    assert "# HELP review_assistant_metadata_backfill_projects_total" in text
    assert "# TYPE review_assistant_metadata_backfill_projects_total counter" in text
    assert "# HELP review_assistant_metadata_backfill_resolutions_total" in text
    assert "# TYPE review_assistant_metadata_backfill_resolutions_total counter" in text
    assert "# EOF" in text
    # Per-status series appear only when at least one resolution row exists
    if "review_assistant_iteration_issue_resolutions{" in text:
        assert "status=" in text
