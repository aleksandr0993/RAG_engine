from pathlib import Path


def test_notebook_review_flow(client):
    sample_path = Path("examples/sample_notebook.ipynb")

    with sample_path.open("rb") as f:
        response = client.post(
            "/api/v1/projects/upload",
            files={"file": ("sample_notebook.ipynb", f, "application/x-ipynb+json")},
        )
    assert response.status_code == 200
    project_id = response.json()["project_id"]

    review_response = client.post(f"/api/v1/projects/{project_id}/review")
    assert review_response.status_code == 200
    payload = review_response.json()
    assert payload["status"] == "done"
    assert payload["final_verdict"] in {"pass", "revise"}

    result_response = client.get(f"/api/v1/projects/{project_id}/review_result")
    assert result_response.status_code == 200
    result_payload = result_response.json()
    assert "review_markdown" in result_payload
    assert result_payload["final_verdict"] == "pass"

    export_response = client.get(f"/api/v1/projects/{project_id}/export/reviewed_notebook")
    assert export_response.status_code == 200
