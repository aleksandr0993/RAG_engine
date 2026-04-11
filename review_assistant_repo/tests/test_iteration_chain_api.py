"""API: iteration_chain and iteration_insights."""

from __future__ import annotations

from pathlib import Path

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook


def _write_ipynb(path: Path, cells: list) -> None:
    nb = new_notebook()
    nb["cells"] = cells
    path.parent.mkdir(parents=True, exist_ok=True)
    nbformat.write(nb, str(path))


def test_iteration_chain_and_insights(client, tmp_path):
    parent_nb = tmp_path / "p.ipynb"
    _write_ipynb(parent_nb, [new_code_cell("x=1\n")])
    with parent_nb.open("rb") as f:
        up1 = client.post(
            "/api/v1/projects/upload",
            files={"file": ("p.ipynb", f, "application/x-ipynb+json")},
        )
    parent_id = up1.json()["project_id"]
    assert client.post(f"/api/v1/projects/{parent_id}/review").status_code == 200

    ch_nb = tmp_path / "c.ipynb"
    _write_ipynb(
        ch_nb,
        [
            new_markdown_cell("## Введение\n\nЦель проекта: x.\n\nОписание данных: y."),
            new_code_cell("import pandas as pd\ndf=pd.DataFrame({'a':[1]})\ndf.head()\ndf.duplicated().sum()\ndf.isna().sum()"),
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
    assert client.post(f"/api/v1/projects/{child_id}/review").status_code == 200

    ch = client.get(f"/api/v1/projects/{child_id}/iteration_chain")
    assert ch.status_code == 200
    body = ch.json()
    assert body["anchor_project_id"] == child_id
    assert body["depth"] == 1
    assert len(body["nodes"]) == 2
    assert body["nodes"][0]["project_id"] == parent_id
    assert body["nodes"][0]["iteration_no"] == 1
    assert body["nodes"][1]["project_id"] == child_id
    assert body["nodes"][1]["parent_project_id"] == parent_id
    assert body["nodes"][1]["iteration_no"] == 2
    for n in body["nodes"]:
        if n["status"] == "done":
            assert n.get("review_turnaround_hours") is not None
            assert n.get("updated_at") is not None

    pch = client.get(f"/api/v1/projects/{parent_id}/iteration_chain")
    assert pch.status_code == 200
    assert len(pch.json()["nodes"]) == 1

    ins = client.get(f"/api/v1/projects/{child_id}/iteration_insights")
    assert ins.status_code == 200
    insb = ins.json()
    assert insb["project_id"] == child_id
    assert insb["stored_resolutions"] >= 1
    assert "fixed" in (insb["resolution_status_histogram"] or {})
    assert "single" in (insb["match_method_histogram"] or {})
    assert insb.get("iteration_fix_policy_version") == "1.1"


def test_iteration_chain_404(client):
    r = client.get("/api/v1/projects/00000000-0000-0000-0000-000000000000/iteration_chain")
    assert r.status_code == 404
