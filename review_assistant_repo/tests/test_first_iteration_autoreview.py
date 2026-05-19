from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

from app.evaluation.first_iteration_autoreview import (
    apply_llm_judge_generator,
    compare_predictions,
    evaluate_first_iteration,
    extract_gold_first_review_comments,
    generate_first_iteration_memory_candidates,
    label_memory_candidates_for_auc,
)
from app.llm.types import LLMCallResult


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


def test_label_memory_candidates_for_auc_marks_tp_fp_and_scores_auc():
    gold = [
        {
            "comment_text": "Названия столбцов приведены к snake_case",
            "criterion_code": "games_columns_snake_case",
            "alert_color": "success",
            "anchor_position_idx": 3,
        }
    ]
    candidates = [
        {
            "comment_text": "Названия столбцов приведены к snake_case",
            "criterion_code": "games_columns_snake_case",
            "alert_color": "success",
            "anchor_position_idx": 3,
            "confidence": 0.9,
        },
        {
            "comment_text": "Проверь пропуски",
            "criterion_code": "games_missing_values_decision",
            "alert_color": "warning",
            "anchor_position_idx": 9,
            "confidence": 0.2,
        },
    ]

    labeled, summary = label_memory_candidates_for_auc(candidates, gold)

    assert [row["auc_label"] for row in labeled] == [1, 0]
    assert summary["roc_auc"] == 1.0
    assert summary["pr_auc_average_precision"] == 1.0
    assert summary["at_threshold"]["f1"] == 1.0
    assert summary["breakdowns"]["by_criterion_code"]["games_columns_snake_case"]["positive_candidates"] == 1


def test_label_memory_candidates_for_auc_handles_edge_cases_and_thresholds():
    candidates = [
        {"comment_text": "Лишний комментарий", "anchor_position_idx": 1, "confidence": 0.8, "status": "memory_warn"},
        {"comment_text": "Еще лишний", "anchor_position_idx": 2, "confidence": 0.4, "status": "memory_warn"},
    ]

    labeled, summary = label_memory_candidates_for_auc(candidates, [], decision_threshold=0.5)

    assert [row["label"] for row in labeled] == [0, 0]
    assert summary["roc_auc"] is None
    assert summary["pr_auc_average_precision"] is None
    assert summary["at_threshold"]["fp"] == 1
    assert summary["at_threshold"]["tn"] == 1
    assert summary["at_threshold"]["f1"] == 0.0


def test_apply_llm_judge_generator_filters_and_rewrites_candidates():
    class FakeLLM:
        is_available = True

        def __init__(self):
            self.calls = 0

        def chat(self, messages, temperature=0.2):
            self.calls += 1
            if self.calls == 1:
                return LLMCallResult(ok=True, text='{"keep": true, "confidence": 0.91, "rationale": "fits"}')
            if self.calls == 2:
                return LLMCallResult(ok=True, text='{"comment_text": "Адаптированный комментарий", "rationale": "clearer"}')
            return LLMCallResult(ok=True, text='{"keep": false, "confidence": 0.82, "rationale": "duplicate"}')

    artifacts = [{"artifact_type": "code_cell", "position_idx": 1, "normalized_text": "df.info()", "metadata_json": {}}]
    candidates = [
        {
            "criterion_code": "games_initial_overview",
            "status": "memory_warn",
            "confidence": 0.9,
            "anchor_position_idx": 1,
            "alert_color": "warning",
            "comment_text": "Старый комментарий",
            "comment_html": "old",
            "metadata": {"source_stage": "memory_retrieval", "memory_candidate_score": 0.9},
        },
        {
            "criterion_code": "games_columns_snake_case",
            "status": "memory_warn",
            "confidence": 0.8,
            "anchor_position_idx": 1,
            "alert_color": "warning",
            "comment_text": "Лишний комментарий",
            "comment_html": "old",
            "metadata": {"source_stage": "memory_retrieval", "memory_candidate_score": 0.8},
        },
    ]

    out = apply_llm_judge_generator(
        candidates,
        artifacts=artifacts,
        llm_service=FakeLLM(),
        enable_judge=True,
        enable_generator=True,
    )

    assert out[0]["comment_text"] == "Адаптированный комментарий"
    assert out[0]["metadata"]["llm_judge_keep"] is True
    assert out[0]["metadata"]["llm_generator_used"] is True
    assert out[0]["metadata"]["source_stage"] == "llm"
    assert out[1]["metadata"]["llm_judge_keep"] is False


def test_apply_llm_judge_generator_accepts_structured_judge_schema():
    class FakeLLM:
        is_available = True
        messages = []

        def chat(self, messages, temperature=0.2):
            self.messages = messages
            return LLMCallResult(
                ok=True,
                text=(
                    '{"keep_score": 0.73, "keep_decision": true, '
                    '"anchor_ok": true, "criterion_ok": false, "reason": "wrong criterion"}'
                ),
            )

    candidates = [
        {
            "criterion_code": "games_initial_overview",
            "status": "memory_warn",
            "confidence": 0.9,
            "anchor_position_idx": 1,
            "alert_color": "warning",
            "comment_text": "Комментарий",
            "comment_html": "old",
            "metadata": {"source_stage": "memory_retrieval"},
        }
    ]
    artifacts = [{"artifact_type": "code_cell", "position_idx": 1, "normalized_text": "df.info()", "metadata_json": {}}]

    fake_llm = FakeLLM()
    out = apply_llm_judge_generator(
        candidates,
        artifacts=artifacts,
        project_memory={
            "missing_requirements": [
                {"criterion_code": "games_initial_overview", "reason": "intro is absent", "evidence_cell_indices": [1]}
            ]
        },
        llm_service=fake_llm,
        enable_judge=True,
    )

    assert out[0]["keep_score"] == 0.73
    assert out[0]["metadata"]["llm_keep_score"] == 0.73
    assert out[0]["metadata"]["llm_anchor_ok"] is True
    assert out[0]["metadata"]["llm_criterion_ok"] is False
    assert out[0]["metadata"]["llm_judge_keep"] is False
    assert "project_memory" in fake_llm.messages[0]["content"]
    assert "intro is absent" in fake_llm.messages[0]["content"]


def test_apply_llm_classifier_and_anchor_validator_updates_and_filters_candidates():
    class FakeLLM:
        is_available = True

        def __init__(self):
            self.calls = 0

        def chat(self, messages, temperature=0.2):
            self.calls += 1
            if self.calls == 1:
                return LLMCallResult(
                    ok=True,
                    text=(
                        '{"comment_kind": "actionable_feedback", '
                        '"criterion_code": "games_columns_snake_case", '
                        '"praise_code": "", "alert_color": "warning", '
                        '"confidence": 0.88, "rationale": "needs fixing"}'
                    ),
                )
            if self.calls == 2:
                return LLMCallResult(ok=True, text='{"valid": true, "confidence": 0.77, "rationale": "near columns"}')
            if self.calls == 3:
                return LLMCallResult(
                    ok=True,
                    text=(
                        '{"comment_kind": "criterion_success", '
                        '"criterion_code": "games_missing_values_decision", '
                        '"praise_code": "", "alert_color": "success", '
                        '"confidence": 0.84, "rationale": "classified"}'
                    ),
                )
            return LLMCallResult(
                ok=True,
                text='{"valid": false, "confidence": 0.81, "rationale": "not nearby", "better_anchor_hint": "look near isna"}',
            )

    artifacts = [
        {
            "artifact_type": "code_cell",
            "position_idx": 1,
            "normalized_text": "df.columns = df.columns.str.lower()",
            "metadata_json": {},
        }
    ]
    candidates = [
        {
            "criterion_code": "",
            "status": "memory_praise",
            "confidence": 0.9,
            "anchor_position_idx": 1,
            "alert_color": "success",
            "comment_kind": "non_criterion_praise",
            "comment_text": "Проверь названия столбцов",
            "comment_html": "old",
            "metadata": {"source_stage": "memory_retrieval", "memory_candidate_score": 0.9},
        },
        {
            "criterion_code": "games_missing_values_decision",
            "status": "memory_success",
            "confidence": 0.8,
            "anchor_position_idx": 1,
            "alert_color": "success",
            "comment_kind": "criterion_success",
            "comment_text": "Отличная обработка пропусков",
            "comment_html": "old",
            "metadata": {"source_stage": "memory_retrieval", "memory_candidate_score": 0.8},
        },
    ]

    out = apply_llm_judge_generator(
        candidates,
        artifacts=artifacts,
        llm_service=FakeLLM(),
        enable_classifier=True,
        enable_anchor_validator=True,
    )

    assert out[0]["comment_kind"] == "actionable_feedback"
    assert out[0]["criterion_code"] == "games_columns_snake_case"
    assert out[0]["status"] == "memory_warn"
    assert out[0]["metadata"]["llm_classifier_used"] is True
    assert out[0]["metadata"]["llm_anchor_valid"] is True
    assert out[0]["metadata"]["source_stage"] == "llm"
    assert out[1]["metadata"]["llm_anchor_valid"] is False
    assert out[1]["metadata"]["llm_anchor_better_hint"] == "look near isna"


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
    assert (tmp_path / "eval" / "all_memory_candidates_labeled.jsonl").exists()
    assert (tmp_path / "eval" / "predicted_reviewed.ipynb").exists()
    assert "candidate_auc" in payload
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

    summary = json.JSONDecoder().raw_decode(result.stdout)[0]
    assert summary["gold_total"] == 1
    assert (tmp_path / "eval_cli" / "comparison.json").exists()


def test_build_first_iteration_candidate_dataset_cli_selects_val_threshold(tmp_path: Path):
    repo = Path(__file__).resolve().parents[1]
    restored = tmp_path / "restored.ipynb"
    reviewed = tmp_path / "reviewed.ipynb"
    _write_nb(restored, [new_code_cell("df.columns = df.columns.str.lower()\ndf.info()")])
    _write_nb(
        reviewed,
        [
            new_code_cell("df.columns = df.columns.str.lower()\ndf.info()"),
            new_markdown_cell(_review_comment("Комментарий ревьюера", "Названия столбцов приведены к snake_case")),
        ],
    )
    memory = tmp_path / "memory.jsonl"
    memory.write_text(
        json.dumps(
            {
                "example_id": "ok-columns",
                "project_type": "python_preprocessing",
                "review_iteration": 1,
                "reviewed_notebook": "other.ipynb",
                "comment_kind": "criterion_success",
                "alert_color": "warning",
                "criterion_code": "games_columns_snake_case",
                "comment_text": "Комментарий ревьюера Названия столбцов приведены к snake_case",
                "anchor_before": {"features": ["columns", "lower"]},
                "local_context": {"before_text": "df.columns = df.columns.str.lower()"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "pairs.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "id": "case-val",
                "split": "val",
                "reviewed": str(reviewed),
                "restored": str(restored),
                "project": "python_preprocessing",
                "criteria_map": "notebook_games_preprocessing_v1",
                "reviewer_insertions_path": str(memory),
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(repo / "scripts" / "build_first_iteration_candidate_dataset.py"),
            "--pairs-jsonl",
            str(manifest),
            "--out-dir",
            str(tmp_path / "dataset"),
            "--memory-candidate-min-score",
            "0.1",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )

    summary = json.JSONDecoder().raw_decode(result.stdout)[0]
    assert summary["threshold_source"] == "val"
    assert summary["candidate_total"] >= 1
    assert summary["by_split"]["val"]["at_threshold"]["f1"] == 1.0
    assert (tmp_path / "dataset" / "candidates_labeled.jsonl").exists()
