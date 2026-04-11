from __future__ import annotations

from pathlib import Path


def test_async_review_returns_job_and_completes(client):
    sample_path = Path("examples/sample_query.sql")
    with sample_path.open("rb") as f:
        up = client.post(
            "/api/v1/projects/upload",
            files={"file": ("sample_query.sql", f, "application/sql")},
        )
    assert up.status_code == 200
    project_id = up.json()["project_id"]

    ar = client.post(f"/api/v1/projects/{project_id}/review/async")
    assert ar.status_code == 202
    body = ar.json()
    job_id = body["job_id"]
    assert job_id != project_id
    assert len(job_id) == 36

    jr = client.get(f"/api/v1/projects/{project_id}/review/jobs/{job_id}")
    assert jr.status_code == 200
    st = jr.json()["status"]
    assert st in {"queued", "running", "done", "failed"}
    # TestClient runs background tasks after response — usually already done
    assert st == "done"

    pr = client.get(f"/api/v1/projects/{project_id}")
    assert pr.status_code == 200
    assert pr.json()["status"] == "done"


def test_get_review_job_404_wrong_project(client):
    sample_path = Path("examples/sample_query.sql")
    with sample_path.open("rb") as f:
        up = client.post(
            "/api/v1/projects/upload",
            files={"file": ("sample_query.sql", f, "application/sql")},
        )
    project_id = up.json()["project_id"]
    ar = client.post(f"/api/v1/projects/{project_id}/review/async")
    job_id = ar.json()["job_id"]
    bad = client.get(f"/api/v1/projects/00000000-0000-0000-0000-000000000000/review/jobs/{job_id}")
    assert bad.status_code == 404
