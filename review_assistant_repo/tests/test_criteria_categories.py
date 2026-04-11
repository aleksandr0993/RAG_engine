import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAPS_DIR = ROOT / "configs" / "criteria_maps"


def test_all_criteria_maps_have_category():
    for path in sorted(MAPS_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for c in data["criteria"]:
            assert "category" in c, f"{path.name} missing category on {c.get('code')}"
            assert isinstance(c["category"], str) and c["category"]


def test_criteria_categories_endpoint(client):
    r = client.get("/api/v1/config/criteria_categories")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, dict)
    assert "structure" in data
    assert "intro_exists" in data["structure"]
    assert "html_has_title" in data["structure"]


def test_findings_category_filter_notebook(client):
    sample_path = Path("examples/sample_notebook.ipynb")
    with sample_path.open("rb") as f:
        up = client.post(
            "/api/v1/projects/upload",
            files={"file": ("sample_notebook.ipynb", f, "application/x-ipynb+json")},
        )
    assert up.status_code == 200
    pid = up.json()["project_id"]
    rev = client.post(f"/api/v1/projects/{pid}/review")
    assert rev.status_code == 200

    all_f = client.get(f"/api/v1/projects/{pid}/findings")
    assert all_f.status_code == 200
    total = len(all_f.json())

    struct = client.get(f"/api/v1/projects/{pid}/findings", params={"category": "structure"})
    assert struct.status_code == 200
    struct_rows = struct.json()
    assert 0 < len(struct_rows) < total
    assert all(x.get("category") == "structure" for x in struct_rows)

    other = client.get(f"/api/v1/projects/{pid}/findings", params={"category": "data_quality"})
    assert other.status_code == 200
    assert all(x.get("category") == "data_quality" for x in other.json())
