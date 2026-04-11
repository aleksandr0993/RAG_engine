from pathlib import Path


def test_html_upload_and_review(client):
    sample_path = Path("examples/sample_html_practicum.html")
    with sample_path.open("rb") as f:
        response = client.post(
            "/api/v1/projects/upload",
            files={"file": ("report.html", f, "text/html")},
        )
    assert response.status_code == 200
    body = response.json()
    project_id = body["project_id"]
    assert body["status"] == "uploaded"

    proj = client.get(f"/api/v1/projects/{project_id}")
    assert proj.json()["source_type"] == "html"
    assert proj.json()["criteria_map_code"] == "html_practicum_v1"

    review = client.post(f"/api/v1/projects/{project_id}/review")
    assert review.status_code == 200
    assert review.json()["status"] == "done"

    findings = client.get(f"/api/v1/projects/{project_id}/findings")
    assert findings.status_code == 200
    rows = findings.json()
    assert len(rows) >= 1
    assert all("category" in r for r in rows)
    codes = {r["criterion_code"] for r in rows}
    assert "html_has_title" in codes
