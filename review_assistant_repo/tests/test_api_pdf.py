from pathlib import Path


def test_pdf_review_flow(client):
    sample_path = Path("examples/sample_dashboard.pdf")
    with sample_path.open("rb") as f:
        response = client.post(
            "/api/v1/projects/upload",
            files={"file": ("sample_dashboard.pdf", f, "application/pdf")},
        )
    assert response.status_code == 200
    project_id = response.json()["project_id"]

    review_response = client.post(f"/api/v1/projects/{project_id}/review")
    assert review_response.status_code == 200
    payload = review_response.json()
    assert payload["status"] == "done"
    assert payload["final_verdict"] == "pass"

    result_response = client.get(f"/api/v1/projects/{project_id}/review_result")
    result = result_response.json()
    codes = {item["criterion_code"] for item in result["findings"]}
    assert "pdf_text_present" in codes
    assert "dashboard_metric_signal" in codes
    assert "pdf_regions_extracted" in codes
    assert "pdf_page_images_saved" in codes
    assert "pdf_image_regions_extracted" in codes
    assert "pdf_overlays_saved" in codes

    files_response = client.get(f"/api/v1/projects/{project_id}/files")
    assert files_response.status_code == 200
    files_payload = files_response.json()
    kinds = {item["kind"] for item in files_payload}
    assert "original" in kinds
    assert "pdf_page_image" in kinds
    assert "pdf_page_overlay" in kinds



def test_pdf_explorer_endpoints(client):
    sample_path = Path("examples/sample_dashboard.pdf")
    with sample_path.open("rb") as f:
        response = client.post(
            "/api/v1/projects/upload",
            files={"file": ("sample_dashboard.pdf", f, "application/pdf")},
        )
    project_id = response.json()["project_id"]

    review_response = client.post(f"/api/v1/projects/{project_id}/review")
    assert review_response.status_code == 200

    artifacts_response = client.get(f"/api/v1/projects/{project_id}/artifacts", params={"artifact_type": "pdf_image_region"})
    assert artifacts_response.status_code == 200
    artifacts = artifacts_response.json()
    assert artifacts, artifacts

    regions_response = client.get(f"/api/v1/projects/{project_id}/regions", params={"source_type": "image"})
    assert regions_response.status_code == 200
    regions = regions_response.json()
    assert regions, regions
    assert any(item["region_kind"] for item in regions)

    first_artifact_id = artifacts[0]["id"]
    artifact_response = client.get(f"/api/v1/projects/{project_id}/artifacts/{first_artifact_id}")
    assert artifact_response.status_code == 200
    assert artifact_response.json()["artifact_type"] == "pdf_image_region"

    summary_response = client.get(f"/api/v1/projects/{project_id}/visual_summary")
    assert summary_response.status_code == 200
    summary = summary_response.json()
    assert summary["artifact_counts"].get("pdf_image_region", 0) >= 1
    assert summary["file_counts"].get("pdf_page_overlay", 0) >= 1
    assert summary["preview_pairs"]
    assert any(pair.get("overlay_file") for pair in summary["preview_pairs"])
