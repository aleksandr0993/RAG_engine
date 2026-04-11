"""
Golden e2e: HTML × Практикум / Revisor — метаданные после ревью для strong/medium/weak.
"""

from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    ("fragment", "expected_confidence", "expected_channel_after_review"),
    [
        (
            '<a href="https://practicum.yandex.ru/learn">курс</a><p>'
            + ("a" * 85)
            + "</p>",
            "strong",
            "revisor",
        ),
        (
            "<p>" + ("b" * 85) + " См. https://practicum.yandex.ru/foo</p>",
            "medium",
            "revisor",
        ),
        (
            "<p>" + ("x" * 30) + " ревизор " + ("y" * 30) + " практикум " + ("z" * 30) + "</p>",
            "weak",
            "html",
        ),
    ],
)
def test_golden_html_practicum_confidence_after_review(
    client,
    tmp_path,
    fragment: str,
    expected_confidence: str,
    expected_channel_after_review: str,
):
    html = f"<!DOCTYPE html><html><body><h1>Отчёт</h1>{fragment}</body></html>"
    path = tmp_path / "g.html"
    path.write_text(html, encoding="utf-8")
    with path.open("rb") as f:
        up = client.post("/api/v1/projects/upload", files={"file": ("g.html", f, "text/html")})
    assert up.status_code == 200
    pid = up.json()["project_id"]
    rv = client.post(f"/api/v1/projects/{pid}/review")
    assert rv.status_code == 200
    meta = client.get(f"/api/v1/projects/{pid}").json()["metadata_json"]
    assert meta.get("practicum_revisor_detection_confidence") == expected_confidence
    assert meta.get("practicum_input_channel") == expected_channel_after_review
    if expected_confidence in ("strong", "medium"):
        assert meta.get("practicum_revisor_html_detected") is True
    else:
        assert meta.get("practicum_revisor_html_detected") is False
