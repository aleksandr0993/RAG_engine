from __future__ import annotations

from pathlib import Path

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

from app.parsers.notebook import MIDDLE_REVIEWER_MARKER, REVIEWER_MARKER, STUDENT_MARKER
from app.retrieval.notebook_training import extract_rows_from_ipynb


def test_extract_runtime_excludes_student(tmp_path: Path):
    nb = new_notebook(
        cells=[
            new_code_cell("import pandas as pd\ndf = pd.read_csv('x.csv')"),
            new_markdown_cell(f"{REVIEWER_MARKER}\n\nНужно обосновать выбор метрики."),
            new_markdown_cell(f"{STUDENT_MARKER}\n\nА если ROC-AUC?"),
            new_markdown_cell(f"{MIDDLE_REVIEWER_MARKER}\n\nСогласен с ревьюером."),
        ]
    )
    p = tmp_path / "m.ipynb"
    nbformat.write(nb, p)
    runtime, finetune = extract_rows_from_ipynb(p, source_project="proj_a", source_notebook="m.ipynb")
    roles_rt = {r["author_role"] for r in runtime}
    assert roles_rt == {"reviewer", "middle_reviewer"}
    roles_ft = {r["author_role"] for r in finetune}
    assert roles_ft == {"reviewer", "middle_reviewer", "student"}
    rev = next(r for r in runtime if r["author_role"] == "reviewer")
    assert "pandas" in rev["student_context"] or "df" in rev["student_context"]
    assert rev["lane"] == "reviewer_style"
    assert rev["source_kind"] == "project_training"
    assert "review_iteration" in rev


def test_extract_training_marks_accepted_lane(tmp_path: Path):
    nb = new_notebook(
        cells=[
            new_code_cell("x = 1"),
            new_markdown_cell(f"{REVIEWER_MARKER}\n\nПринято, хороший вывод."),
        ],
        metadata={"final_verdict": "pass"},
    )
    p = tmp_path / "accepted.ipynb"
    nbformat.write(nb, p)

    runtime, _finetune = extract_rows_from_ipynb(p, source_project="proj_a")

    assert runtime[0]["lane"] == "accepted_patterns"
    assert runtime[0]["final_verdict"] == "accepted"
    assert "accepted_patterns" in runtime[0]["tags"]
