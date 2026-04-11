from pathlib import Path


def test_sql_review_flow_pass(client):
    sample_path = Path("examples/sample_query.sql")
    with sample_path.open("rb") as f:
        response = client.post(
            "/api/v1/projects/upload",
            files={"file": ("sample_query.sql", f, "text/plain")},
        )
    assert response.status_code == 200
    project_id = response.json()["project_id"]

    review_response = client.post(f"/api/v1/projects/{project_id}/review")
    assert review_response.status_code == 200
    assert review_response.json()["final_verdict"] == "pass"


def test_sql_review_flow_revise(client):
    sample_path = Path("examples/sample_query_bad.sql")
    with sample_path.open("rb") as f:
        response = client.post(
            "/api/v1/projects/upload",
            files={"file": ("sample_query_bad.sql", f, "text/plain")},
        )
    assert response.status_code == 200
    project_id = response.json()["project_id"]

    review_response = client.post(f"/api/v1/projects/{project_id}/review")
    assert review_response.status_code == 200
    assert review_response.json()["final_verdict"] == "revise"
