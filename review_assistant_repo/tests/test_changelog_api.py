import tomllib
from pathlib import Path


def _pyproject_version() -> str:
    root = Path(__file__).resolve().parents[1]
    with (root / "pyproject.toml").open("rb") as f:
        return tomllib.load(f)["project"]["version"]


def test_changelog_json(client):
    r = client.get("/api/v1/changelog")
    assert r.status_code == 200
    data = r.json()
    assert "package_version" in data
    assert data.get("source_path") == "CHANGELOG.md"
    entries = data["entries"]
    assert len(entries) >= 1
    manifest_version = _pyproject_version()
    assert entries[0]["version"] == manifest_version, (
        "Top CHANGELOG.md section must match [project].version in pyproject.toml"
    )
    assert data["package_version"] == entries[0]["version"], (
        "importlib.metadata version must match CHANGELOG after `pip install -e .`"
    )
    assert len(entries[0]["items"]) >= 1
    assert any("GET /api/v1/changelog" in item for e in entries for item in e.get("items", []))


def test_changelog_limit(client):
    r = client.get("/api/v1/changelog", params={"limit": 1})
    assert r.status_code == 200
    assert len(r.json()["entries"]) == 1
