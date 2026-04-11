from pathlib import Path


def test_visual_summary_includes_extended_fields(client):
    sample_path = Path("examples/sample_dashboard.pdf")
    with sample_path.open("rb") as f:
        response = client.post(
            "/api/v1/projects/upload",
            files={"file": ("sample_dashboard.pdf", f, "application/pdf")},
        )
    project_id = response.json()["project_id"]
    client.post(f"/api/v1/projects/{project_id}/review")

    summary = client.get(f"/api/v1/projects/{project_id}/visual_summary").json()
    assert "image_region_count" in summary
    assert "text_region_count" in summary
    assert "low_text_extraction_pages" in summary
    assert "low_region_confidence_pages" in summary

    preview = client.get(f"/api/v1/projects/{project_id}/visual_preview", params={"page_no": 0})
    assert preview.status_code == 200
    body = preview.json()
    assert "regions" in body
    assert "metadata_summary" in body
