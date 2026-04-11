from __future__ import annotations

import pytest

from app.utils.practicum_input import normalize_practicum_input_channel


def test_normalize_auto_ipynb():
    ch, fl = normalize_practicum_input_channel(None, source_type="ipynb")
    assert ch == "jupyter"
    assert fl["explicit"] is False


def test_normalize_auto_html():
    ch, fl = normalize_practicum_input_channel("auto", source_type="html")
    assert ch == "html"
    assert fl["explicit"] is False


def test_normalize_explicit_revisor_any():
    ch, fl = normalize_practicum_input_channel("revisor", source_type="sql")
    assert ch == "revisor"
    assert fl["explicit"] is True


def test_normalize_jupyter_requires_ipynb():
    with pytest.raises(ValueError, match="jupyter"):
        normalize_practicum_input_channel("jupyter", source_type="sql")


def test_upload_practicum_metadata_jupyter(client):
    from pathlib import Path

    p = Path("examples/sample_notebook.ipynb")
    with p.open("rb") as f:
        r = client.post(
            "/api/v1/projects/upload",
            files={"file": ("sample_notebook.ipynb", f, "application/x-ipynb+json")},
            data={"practicum_input_channel": "jupyter"},
        )
    assert r.status_code == 200
    pid = r.json()["project_id"]
    proj = client.get(f"/api/v1/projects/{pid}").json()
    assert proj["metadata_json"]["practicum_input_channel"] == "jupyter"
    assert proj["metadata_json"]["practicum_input_explicit"] is True


def test_upload_practicum_revisor_sql(client):
    from pathlib import Path

    p = Path("examples/sample_query.sql")
    with p.open("rb") as f:
        r = client.post(
            "/api/v1/projects/upload",
            files={"file": ("sample_query.sql", f, "application/sql")},
            data={"practicum_input_channel": "revisor"},
        )
    assert r.status_code == 200
    meta = client.get(f"/api/v1/projects/{r.json()['project_id']}").json()["metadata_json"]
    assert meta["practicum_input_channel"] == "revisor"


def test_html_practicum_hint_upgrades_channel_after_review(client, tmp_path):
    html = (
        "<!DOCTYPE html><html><body><h1>Отчёт</h1><p>"
        + ("x" * 85)
        + '</p><a href="https://practicum.yandex.ru/learn">курс</a></body></html>'
    )
    fpath = tmp_path / "p.html"
    fpath.write_text(html, encoding="utf-8")
    with fpath.open("rb") as f:
        r = client.post("/api/v1/projects/upload", files={"file": ("p.html", f, "text/html")})
    assert r.status_code == 200
    pid = r.json()["project_id"]
    assert client.get(f"/api/v1/projects/{pid}").json()["metadata_json"]["practicum_input_channel"] == "html"
    client.post(f"/api/v1/projects/{pid}/review")
    meta = client.get(f"/api/v1/projects/{pid}").json()["metadata_json"]
    assert meta["practicum_revisor_html_detected"] is True
    assert meta["practicum_revisor_detection_confidence"] in ("strong", "medium")
    assert meta["practicum_input_channel"] == "revisor"


def test_weak_html_does_not_upgrade_channel_after_review(client, tmp_path):
    body = "<p>" + "x" * 30 + " ревизор " + "y" * 30 + " практикум " + "z" * 30 + "</p>"
    html = f"<!DOCTYPE html><html><body>{body}</body></html>"
    fpath = tmp_path / "weak.html"
    fpath.write_text(html, encoding="utf-8")
    with fpath.open("rb") as f:
        r = client.post("/api/v1/projects/upload", files={"file": ("weak.html", f, "text/html")})
    assert r.status_code == 200
    pid = r.json()["project_id"]
    client.post(f"/api/v1/projects/{pid}/review")
    meta = client.get(f"/api/v1/projects/{pid}").json()["metadata_json"]
    assert meta["practicum_revisor_detection_confidence"] == "weak"
    assert meta["practicum_input_channel"] == "html"


def test_upload_jupyter_on_sql_400(client):
    from pathlib import Path

    p = Path("examples/sample_query.sql")
    with p.open("rb") as f:
        r = client.post(
            "/api/v1/projects/upload",
            files={"file": ("sample_query.sql", f, "application/sql")},
            data={"practicum_input_channel": "jupyter"},
        )
    assert r.status_code == 400
