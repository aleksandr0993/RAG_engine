"""API: iteration_metrics and recent iteration metrics dashboard."""

from __future__ import annotations

from pathlib import Path

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook


def _write_ipynb(path: Path, cells: list) -> None:
    nb = new_notebook()
    nb["cells"] = cells
    path.parent.mkdir(parents=True, exist_ok=True)
    nbformat.write(nb, str(path))


def _two_iteration_setup(client, tmp_path):
    parent_nb = tmp_path / "p.ipynb"
    _write_ipynb(parent_nb, [new_code_cell("x=1\n")])
    with parent_nb.open("rb") as f:
        up1 = client.post(
            "/api/v1/projects/upload",
            files={"file": ("p.ipynb", f, "application/x-ipynb+json")},
        )
    parent_id = up1.json()["project_id"]
    client.post(f"/api/v1/projects/{parent_id}/review")

    ch_nb = tmp_path / "c.ipynb"
    _write_ipynb(
        ch_nb,
        [
            new_markdown_cell("## Введение\n\nЦель проекта: x.\n\nОписание данных: y."),
            new_code_cell(
                "import pandas as pd\n"
                "df=pd.DataFrame({'a':[1]})\n"
                "df.head()\n"
                "df.duplicated().sum()\n"
                "df.isna().sum()"
            ),
            new_markdown_cell("## Вывод\n\nИтог."),
        ],
    )
    with ch_nb.open("rb") as f:
        up2 = client.post(
            "/api/v1/projects/upload",
            files={"file": ("c.ipynb", f, "application/x-ipynb+json")},
            data={"previous_project_id": parent_id},
        )
    child_id = up2.json()["project_id"]
    client.post(f"/api/v1/projects/{child_id}/review")
    return parent_id, child_id


def test_iteration_metrics_for_leaf_and_recent_dashboard(client, tmp_path):
    parent_id, child_id = _two_iteration_setup(client, tmp_path)

    r = client.get(f"/api/v1/projects/{child_id}/iteration_metrics")
    assert r.status_code == 200
    body = r.json()
    assert body["anchor_project_id"] == child_id
    assert body["chain_length"] == 2
    assert body.get("chain_submission_span_hours") is not None
    assert body.get("iteration_fix_policy_version") == "1.1"
    assert body["anchor"]["rates"]["total"] >= 1
    assert body["anchor"]["rates"].get("fixed_rate") is not None
    assert body["chain_rollup"]["total_resolution_records"] >= body["anchor"]["rates"]["total"]
    assert len(body["by_iteration"]) >= 1
    step = next(s for s in body["by_iteration"] if s["project_id"] == child_id)
    assert step["rates"]["total"] >= 1
    assert step.get("hours_since_prior_iteration") is not None
    assert any(c["criterion_code"] for c in step["criterion_breakdown"])

    glob = client.get("/api/v1/projects/iteration_metrics/by_criterion?max_rows=5000&limit=20")
    assert glob.status_code == 200
    gb = glob.json()
    assert gb["sampled_resolution_rows"] >= 1
    assert gb["overall_rates"]["total"] >= 1
    assert len(gb["by_criterion"]) >= 1
    assert gb.get("full_scan") is False
    top = gb["by_criterion"][0]
    assert "criterion_code" in top
    assert top["total"] >= 1

    gbf = client.get("/api/v1/projects/iteration_metrics/by_criterion?full_scan=true&limit=10")
    assert gbf.status_code == 200
    assert gbf.json().get("full_scan") is True
    assert gbf.json()["max_rows_cap"] >= 1000

    assert step.get("review_turnaround_hours") is not None

    recent = client.get("/api/v1/projects/iteration_metrics/recent?limit=10")
    assert recent.status_code == 200
    items = recent.json()["items"]
    assert any(row["project_id"] == child_id for row in items)
    row = next(x for x in items if x["project_id"] == child_id)
    assert row["total_issues_addressed"] >= 1
    assert row["rates"]["fixed"] >= 1


def test_iteration_metrics_404(client):
    assert (
        client.get("/api/v1/projects/00000000-0000-0000-0000-000000000000/iteration_metrics").status_code
        == 404
    )


def test_recent_iteration_metrics_empty_ok(client):
    r = client.get("/api/v1/projects/iteration_metrics/recent?limit=5")
    assert r.status_code == 200
    assert r.json()["items"] == []


def test_global_criterion_rollup_empty_db(client):
    r = client.get("/api/v1/projects/iteration_metrics/by_criterion?max_rows=500&limit=10")
    assert r.status_code == 200
    b = r.json()
    assert b["sampled_resolution_rows"] == 0
    assert b["by_criterion"] == []
    assert b.get("full_scan") is False
