"""Разбор строки CSV в dict для RawHomeworkRecord (ручная выгрузка ревьюеров)."""

from __future__ import annotations

import json
from typing import Any

REQUIRED = (
    "id",
    "student_id",
    "assignment_id",
    "submission_text",
    "review_text",
    "overall_score",
)
OPTIONAL_STR = (
    "task_type",
    "language",
    "reviewer_id",
    "assignment_prompt",
    "rubric_text",
    "revision_history",
    "student_profile",
)


def clean_cell(v: str | None) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def row_to_record_dict(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in REQUIRED:
        if k not in row or clean_cell(row.get(k)) is None:
            raise ValueError(f"отсутствует или пусто обязательное поле: {k}")
        if k == "overall_score":
            out[k] = row[k]
        else:
            out[k] = clean_cell(row[k])

    out["overall_score"] = float(str(out["overall_score"]).replace(",", "."))

    for k in OPTIONAL_STR:
        raw = clean_cell(row.get(k))
        if raw is not None:
            out[k] = raw

    rs = clean_cell(row.get("rubric_scores"))
    if rs is not None:
        out["rubric_scores"] = json.loads(rs)

    ex = clean_cell(row.get("extra"))
    if ex is not None:
        out["extra"] = json.loads(ex)
    else:
        out["extra"] = {}

    return out
