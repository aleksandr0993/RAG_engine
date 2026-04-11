from pathlib import Path

from PIL import Image, ImageDraw

from app.capture.datalens import DataLensCaptureService


def test_datalens_review_flow(client):
    response = client.post(
        "/api/v1/projects/upload",
        data={"source_url": "https://datalens.yandex/abcd1234"},
    )
    assert response.status_code == 200
    project_id = response.json()["project_id"]

    review_response = client.post(f"/api/v1/projects/{project_id}/review")
    assert review_response.status_code == 200
    payload = review_response.json()
    assert payload["status"] == "done"
    assert payload["final_verdict"] == "pass"

    result_response = client.get(f"/api/v1/projects/{project_id}/review_result")
    assert result_response.status_code == 200
    result = result_response.json()
    codes = {item["criterion_code"] for item in result["findings"]}
    assert "datalens_url_quality" in codes
    assert "datalens_regions_inferred" in codes


def test_datalens_capture_screenshots_are_saved(client, monkeypatch, tmp_path):
    screenshot_path = tmp_path / "fake_capture.png"
    screenshot_path.write_bytes(b"fakepng")

    def fake_capture(self, source_url: str, capture_dir: str | None = None) -> dict:
        if capture_dir:
            Path(capture_dir).mkdir(parents=True, exist_ok=True)
            target = Path(capture_dir) / "capture.png"
            target.write_bytes(screenshot_path.read_bytes())
            stored = str(target)
        else:
            stored = str(screenshot_path)
        return {
            "source_url": source_url,
            "domain": "datalens.yandex",
            "path_segments": ["abcd1234"],
            "capture_available": True,
            "capture_status": "captured",
            "capture_method": "fake",
            "screenshot_paths": [stored],
            "title": "Revenue dashboard",
            "text_fragments": ["Filter: country", "KPI revenue", "Chart by week"],
            "generated_files": [],
        }

    monkeypatch.setattr(DataLensCaptureService, "capture", fake_capture)

    response = client.post(
        "/api/v1/projects/upload",
        data={"source_url": "https://datalens.yandex/abcd1234"},
    )
    assert response.status_code == 200
    project_id = response.json()["project_id"]

    review_response = client.post(f"/api/v1/projects/{project_id}/review")
    assert review_response.status_code == 200
    assert review_response.json()["final_verdict"] == "pass"

    files_response = client.get(f"/api/v1/projects/{project_id}/files")
    assert files_response.status_code == 200
    payload = files_response.json()
    screenshot_files = [item for item in payload if item["kind"] == "capture_screenshot"]
    assert screenshot_files, payload

    download_response = client.get(f"/api/v1/projects/{project_id}/files/{screenshot_files[0]['id']}")
    assert download_response.status_code == 200


def test_datalens_image_regions_and_overlay_are_saved(client, monkeypatch, tmp_path):
    def fake_capture(self, source_url: str, capture_dir: str | None = None) -> dict:
        capture_root = Path(capture_dir or tmp_path)
        capture_root.mkdir(parents=True, exist_ok=True)
        image_path = capture_root / "capture_visual.png"
        img = Image.new("RGB", (900, 600), "white")
        draw = ImageDraw.Draw(img)
        draw.rectangle([40, 30, 860, 95], outline="black", width=3)
        draw.rectangle([40, 120, 260, 220], outline="black", width=3)
        draw.rectangle([300, 120, 520, 220], outline="black", width=3)
        draw.rectangle([40, 260, 860, 560], outline="black", width=3)
        img.save(image_path)
        return {
            "source_url": source_url,
            "domain": "datalens.yandex",
            "path_segments": ["visualdemo"],
            "capture_available": True,
            "capture_status": "captured",
            "capture_method": "fake_visual",
            "screenshot_paths": [str(image_path)],
            "title": "Revenue dashboard",
            "text_fragments": ["Filter by country", "KPI revenue", "Chart by week"],
            "generated_files": [],
        }

    monkeypatch.setattr(DataLensCaptureService, "capture", fake_capture)

    response = client.post(
        "/api/v1/projects/upload",
        data={"source_url": "https://datalens.yandex/visualdemo"},
    )
    assert response.status_code == 200
    project_id = response.json()["project_id"]

    review_response = client.post(f"/api/v1/projects/{project_id}/review")
    assert review_response.status_code == 200
    assert review_response.json()["final_verdict"] == "pass"

    result_response = client.get(f"/api/v1/projects/{project_id}/review_result")
    result = result_response.json()
    findings = {item["criterion_code"]: item for item in result["findings"]}
    assert findings["datalens_image_regions_extracted"]["status"] == "pass"
    assert findings["datalens_capture_overlays_saved"]["status"] == "pass"

    files_response = client.get(f"/api/v1/projects/{project_id}/files")
    payload = files_response.json()
    kinds = {item["kind"] for item in payload}
    assert "capture_screenshot" in kinds
    assert "capture_overlay" in kinds



def test_datalens_explorer_endpoints(client, monkeypatch, tmp_path):
    def fake_capture(self, source_url: str, capture_dir: str | None = None) -> dict:
        capture_root = Path(capture_dir or tmp_path)
        capture_root.mkdir(parents=True, exist_ok=True)
        image_path = capture_root / "capture_visual_2.png"
        img = Image.new("RGB", (1000, 650), "white")
        draw = ImageDraw.Draw(img)
        draw.rectangle([40, 30, 960, 110], outline="black", width=3)
        draw.rectangle([40, 140, 280, 240], outline="black", width=3)
        draw.rectangle([320, 140, 560, 240], outline="black", width=3)
        draw.rectangle([40, 280, 960, 610], outline="black", width=3)
        img.save(image_path)
        return {
            "source_url": source_url,
            "domain": "datalens.yandex",
            "path_segments": ["visualdemo2"],
            "capture_available": True,
            "capture_status": "captured",
            "capture_method": "fake_visual",
            "screenshot_paths": [str(image_path)],
            "title": "Revenue dashboard 2",
            "text_fragments": ["Filter by city", "KPI retention", "Chart by month"],
            "generated_files": [],
        }

    monkeypatch.setattr(DataLensCaptureService, "capture", fake_capture)

    response = client.post(
        "/api/v1/projects/upload",
        data={"source_url": "https://datalens.yandex/visualdemo2"},
    )
    project_id = response.json()["project_id"]
    review_response = client.post(f"/api/v1/projects/{project_id}/review")
    assert review_response.status_code == 200

    regions_response = client.get(f"/api/v1/projects/{project_id}/regions", params={"source_type": "image"})
    assert regions_response.status_code == 200
    regions = regions_response.json()
    assert regions, regions
    assert any(item["artifact_type"] == "datalens_image_region" for item in regions)

    summary_response = client.get(f"/api/v1/projects/{project_id}/visual_summary")
    assert summary_response.status_code == 200
    summary = summary_response.json()
    assert summary["file_counts"].get("capture_screenshot", 0) >= 1
    assert summary["file_counts"].get("capture_overlay", 0) >= 1
    assert summary["preview_pairs"]
    assert any(pair.get("base_file") for pair in summary["preview_pairs"])

    artifacts_response = client.get(f"/api/v1/projects/{project_id}/artifacts", params={"artifact_type": "datalens_capture_overlay"})
    assert artifacts_response.status_code == 200
    overlays = artifacts_response.json()
    assert overlays, overlays
