from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

from app.evaluation.first_iteration_autoreview import (
    compare_predictions,
    evaluate_first_iteration,
    extract_gold_first_review_comments,
    generate_first_iteration_memory_candidates,
)


def _write_nb(path: Path, cells: list) -> None:
    nbformat.write(new_notebook(cells=cells), path)


def _review_comment(label: str, text: str = "Добавь описание проекта") -> str:
    return (
        '<div class="alert alert-warning">'
        f"<h2>{label}</h2>"
        f"{text}"
        "</div>"
    )


def test_extract_gold_first_review_comments_excludes_explicit_versions_and_final(tmp_path: Path):
    restored = tmp_path / "restored.ipynb"
    reviewed = tmp_path / "reviewed.ipynb"
    _write_nb(restored, [new_code_cell("df.info()")])
    _write_nb(
        reviewed,
        [
            new_code_cell("df.info()"),
            new_markdown_cell(_review_comment("Комментарий ревьюера", "Добавь описание проекта")),
            new_markdown_cell(_review_comment("Комментарий ревьюера 2", "Повторная проверка")),
            new_markdown_cell(
                '<div><h2>Итоговый комментарий ревьюера</h2>'
                "Теперь почти идеально, молодец! Принимаю твой проект)</div>"
            ),
        ],
    )

    rows = extract_gold_first_review_comments(
        restored_notebook=restored,
        reviewed_notebook=reviewed,
        project="python_preprocessing",
    )

    assert len(rows) == 1
    assert rows[0]["comment_text"].endswith("Добавь описание проекта")
    assert rows[0]["anchor_position_idx"] == 0


def test_compare_predictions_counts_match_missed_and_extra():
    gold = [
        {
            "comment_text": "Добавь описание проекта",
            "criterion_code": "games_project_intro",
            "alert_color": "danger",
            "anchor_position_idx": 2,
            "comment_kind": "actionable_feedback",
        },
        {
            "comment_text": "Отличная предобработка",
            "criterion_code": "games_missing_values_decision",
            "alert_color": "success",
            "anchor_position_idx": 5,
            "comment_kind": "criterion_success",
        },
    ]
    predicted = [
        {
            "comment_text": "Добавь описание проекта",
            "criterion_code": "games_project_intro",
            "alert_color": "danger",
            "anchor_position_idx": 3,
            "status": "fail",
        },
        {
            "comment_text": "Проверь дубликаты",
            "criterion_code": "games_duplicates_checked",
            "alert_color": "warning",
            "anchor_position_idx": 8,
            "status": "warn",
        },
    ]

    comparison = compare_predictions(predicted, gold)

    assert comparison["summary"]["matched_total"] == 1
    assert comparison["summary"]["missed_total"] == 1
    assert comparison["summary"]["extra_total"] == 1
    assert comparison["summary"]["anchor_within_1"] == 1


def test_generate_first_iteration_memory_candidates_uses_success_and_praise_rows():
    artifacts = [
        {
            "artifact_type": "code_cell",
            "position_idx": 3,
            "normalized_text": "df.columns = df.columns.str.lower()\ndf.info()",
            "metadata_json": {},
        }
    ]
    memory_rows = [
        {
            "example_id": "ok-columns",
            "project_type": "python_preprocessing",
            "review_iteration": 1,
            "reviewed_notebook": "other.ipynb",
            "comment_kind": "criterion_success",
            "alert_color": "success",
            "criterion_code": "games_columns_snake_case",
            "comment_text": "Комментарий ревьюера Все отлично! Названия столбцов приведены к snake_case.",
            "anchor_before": {"features": ["columns", "lower"]},
            "local_context": {"before_text": "df.columns = df.columns.str.lower()"},
        },
        {
            "example_id": "v2",
            "project_type": "python_preprocessing",
            "review_iteration": 2,
            "reviewed_notebook": "other.ipynb",
            "comment_kind": "criterion_success",
            "alert_color": "success",
            "criterion_code": "games_columns_snake_case",
            "comment_text": "Комментарий ревьюера 2 Все отлично!",
            "anchor_before": {"features": ["columns", "lower"]},
            "local_context": {"before_text": "df.columns = df.columns.str.lower()"},
        },
    ]

    rows = generate_first_iteration_memory_candidates(
        artifacts=artifacts,
        memory_rows=memory_rows,
        project="python_preprocessing",
        min_score=0.2,
    )

    assert len(rows) == 1
    assert rows[0]["status"] == "memory_success"
    assert rows[0]["anchor_position_idx"] == 3
    assert rows[0]["metadata"]["source_stage"] == "memory_retrieval"


def test_evaluate_first_iteration_writes_artifacts(tmp_path: Path):
    restored = tmp_path / "restored.ipynb"
    reviewed = tmp_path / "reviewed.ipynb"
    _write_nb(restored, [new_code_cell("x = 1")])
    _write_nb(
        reviewed,
        [
            new_code_cell("x = 1"),
            new_markdown_cell(_review_comment("Комментарий ревьюера", "Добавь описание проекта")),
        ],
    )

    payload = evaluate_first_iteration(
        reviewed_notebook=reviewed,
        restored_notebook=restored,
        project="python_preprocessing",
        criteria_map="notebook_games_preprocessing_v1",
        out_dir=tmp_path / "eval",
        reviewer_insertions_path=None,
        include_memory_candidates=False,
    )

    assert payload["comparison"]["summary"]["gold_total"] == 1
    assert (tmp_path / "eval" / "gold_first_review_comments.jsonl").exists()
    assert (tmp_path / "eval" / "predicted_insertions.jsonl").exists()
    assert (tmp_path / "eval" / "predicted_reviewed.ipynb").exists()
    assert "First-iteration autoreview evaluation" in (tmp_path / "eval" / "report.md").read_text(encoding="utf-8")


def test_evaluate_first_iteration_cli(tmp_path: Path):
    repo = Path(__file__).resolve().parents[1]
    restored = tmp_path / "restored.ipynb"
    reviewed = tmp_path / "reviewed.ipynb"
    _write_nb(restored, [new_code_cell("x = 1")])
    _write_nb(reviewed, [new_code_cell("x = 1"), new_markdown_cell(_review_comment("Комментарий ревьюера"))])

    result = subprocess.run(
        [
            sys.executable,
            str(repo / "scripts" / "evaluate_first_iteration_autoreview.py"),
            "--reviewed",
            str(reviewed),
            "--restored",
            str(restored),
            "--out-dir",
            str(tmp_path / "eval_cli"),
            "--reviewer-insertions-path",
            str(tmp_path / "missing.jsonl"),
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )

    summary = json.loads(result.stdout.split("report_md=")[0])
    assert summary["gold_total"] == 1
    assert (tmp_path / "eval_cli" / "comparison.json").exists()
