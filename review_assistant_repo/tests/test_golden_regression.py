"""
Golden-style regression: real parsers + rule engine on committed example assets.
Asserts v0.9 observability fields and stable source_stage values.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.finding_policy import SOURCE_STAGES

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.mark.parametrize("rel_path", ["sample_notebook.ipynb", "sample_query.sql", "sample_dashboard.pdf"])
def test_golden_file_review_metadata(client, rel_path: str):
    path = EXAMPLES / rel_path
    with path.open("rb") as f:
        up = client.post(
            "/api/v1/projects/upload",
            files={"file": (path.name, f, "application/octet-stream")},
        )
    assert up.status_code == 200, up.text
    project_id = up.json()["project_id"]
    rv = client.post(f"/api/v1/projects/{project_id}/review")
    assert rv.status_code == 200, rv.text
    proj = client.get(f"/api/v1/projects/{project_id}").json()
    meta = proj["metadata_json"]
    assert "review_pipeline_timeline" in meta
    assert isinstance(meta["review_pipeline_timeline"], list)
    assert meta["review_pipeline_timeline"], "timeline should have stages"
    assert "quality_summary" in meta
    assert "manual_review_needed" in meta["quality_summary"]
    summ = meta.get("criteria_execution_summary") or {}
    assert "by_source_stage" in summ
    assert "by_source_stage_status" in summ

    findings = client.get(f"/api/v1/projects/{project_id}/findings").json()
    for frow in findings:
        stage = (frow.get("metadata_json") or {}).get("source_stage")
        assert stage in SOURCE_STAGES, stage

    tl = client.get(f"/api/v1/projects/{project_id}/debug/review_timeline")
    assert tl.status_code == 200
    body = tl.json()
    assert "review_pipeline_timeline" in body
    assert "quality_summary" in body


def test_golden_datalens_review_metadata(client):
    response = client.post(
        "/api/v1/projects/upload",
        data={"source_url": "https://datalens.yandex/abcd1234"},
    )
    assert response.status_code == 200
    project_id = response.json()["project_id"]
    rv = client.post(f"/api/v1/projects/{project_id}/review")
    assert rv.status_code == 200
    proj = client.get(f"/api/v1/projects/{project_id}").json()
    meta = proj["metadata_json"]
    assert "review_pipeline_timeline" in meta
    assert "quality_summary" in meta
