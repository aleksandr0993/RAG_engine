"""Iteration linkage + snapshot-based fix verification (API integration)."""

from __future__ import annotations

from pathlib import Path

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook


def _write_ipynb(path: Path, cells: list) -> None:
    nb = new_notebook()
    nb["cells"] = cells
    path.parent.mkdir(parents=True, exist_ok=True)
    nbformat.write(nb, str(path))


def test_iteration_fix_summary_after_parent_reviewed_and_child_linked(client, tmp_path):
    """Parent fails structure checks; child fixes them; iteration summary reports fixes."""
    parent_nb = tmp_path / "parent.ipynb"
    _write_ipynb(
        parent_nb,
        [
            new_code_cell("x = 1\n"),
        ],
    )
    with parent_nb.open("rb") as f:
        up1 = client.post(
            "/api/v1/projects/upload",
            files={"file": ("parent.ipynb", f, "application/x-ipynb+json")},
        )
    assert up1.status_code == 200
    parent_id = up1.json()["project_id"]

    r1 = client.post(f"/api/v1/projects/{parent_id}/review")
    assert r1.status_code == 200

    child_nb = tmp_path / "child.ipynb"
    _write_ipynb(
        child_nb,
        [
            new_markdown_cell("## Введение\n\nЦель проекта: проверка итераций.\n\nОписание данных: тест."),
            new_code_cell(
                "import pandas as pd\n"
                "df = pd.DataFrame({'a': [1, 1, None], 'b': [1, 2, 3]})\n"
                "df.head()\n"
                "df.duplicated().sum()\n"
                "df.isna().sum()\n"
            ),
            new_markdown_cell("## Вывод\n\nИтог: данные обработаны, дубликаты и пропуски проверены."),
        ],
    )
    with child_nb.open("rb") as f:
        up2 = client.post(
            "/api/v1/projects/upload",
            files={"file": ("child.ipynb", f, "application/x-ipynb+json")},
            data={"previous_project_id": parent_id},
        )
    assert up2.status_code == 200
    child_id = up2.json()["project_id"]

    r2 = client.post(f"/api/v1/projects/{child_id}/review")
    assert r2.status_code == 200

    res = client.get(f"/api/v1/projects/{child_id}/review_result")
    assert res.status_code == 200
    body = res.json()
    summary = body.get("iteration_fix_summary") or {}
    assert summary.get("has_parent_link") is True
    assert summary.get("status") == "evaluated"
    counts = summary.get("counts") or {}
    assert counts.get("total_previous_issues", 0) >= 1
    assert counts.get("fixed", 0) >= 1
    assert summary.get("iteration_fix_policy_version") == "1.1"
    assert "Проверка исправлений прошлой итерации" in (body.get("review_markdown") or "")


def test_upload_rejects_mismatched_previous_project_source_type(client, tmp_path):
    sql_path = Path("examples/sample_query.sql")
    with sql_path.open("rb") as f:
        up_sql = client.post(
            "/api/v1/projects/upload",
            files={"file": ("sample_query.sql", f, "application/sql")},
        )
    assert up_sql.status_code == 200
    sql_id = up_sql.json()["project_id"]

    nb_path = tmp_path / "x.ipynb"
    _write_ipynb(nb_path, [new_code_cell("1+1")])
    with nb_path.open("rb") as f:
        bad = client.post(
            "/api/v1/projects/upload",
            files={"file": ("x.ipynb", f, "application/x-ipynb+json")},
            data={"previous_project_id": sql_id},
        )
    assert bad.status_code == 400
