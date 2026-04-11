from pathlib import Path


def test_findings_filters_and_artifact_section_filter(client):
    sample_path = Path("examples/sample_notebook.ipynb")
    with sample_path.open("rb") as f:
        r = client.post(
            "/api/v1/projects/upload",
            files={"file": ("sample_notebook.ipynb", f, "application/x-ipynb+json")},
        )
    project_id = r.json()["project_id"]
    client.post(f"/api/v1/projects/{project_id}/review")

    all_findings = client.get(f"/api/v1/projects/{project_id}/findings").json()
    assert all_findings

    one = client.get(
        f"/api/v1/projects/{project_id}/findings",
        params={"criterion_code": all_findings[0]["criterion_code"]},
    ).json()
    assert len(one) == 1

    staged = client.get(
        f"/api/v1/projects/{project_id}/findings",
        params={"source_stage": "rule"},
    ).json()
    assert isinstance(staged, list)
    assert len(staged) <= len(all_findings)

    arts = client.get(
        f"/api/v1/projects/{project_id}/artifacts",
        params={"section_name": "intro"},
    ).json()
    assert isinstance(arts, list)

    crit = client.get(f"/api/v1/projects/{project_id}/debug/criteria_summary").json()
    assert crit.get("total", 0) >= 1
