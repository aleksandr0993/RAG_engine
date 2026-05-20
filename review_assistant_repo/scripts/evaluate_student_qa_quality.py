"""Offline quality evaluation for Student Q&A answers stored in metadata or JSONL."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.evaluation.quality_metrics import (
    aggregate_quality_evals,
    evaluate_student_qa_rows_quality,
    render_quality_summary_markdown,
)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def _answers_from_json(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if not isinstance(data, dict):
        return []
    if isinstance(data.get("student_question_answers"), list):
        return [row for row in data["student_question_answers"] if isinstance(row, dict)]
    metadata = data.get("metadata_json") if isinstance(data.get("metadata_json"), dict) else data
    answers = metadata.get("student_question_answers") if isinstance(metadata, dict) else None
    return [row for row in answers if isinstance(row, dict)] if isinstance(answers, list) else []


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--answers-jsonl", type=Path, help="JSONL with one student Q&A answer per line.")
    src.add_argument("--answers-json", type=Path, help="JSON list or project/metadata JSON containing student_question_answers.")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--quality-judge-model", default=None)
    parser.add_argument("--quality-judge-max-items", type=int, default=100)
    parser.add_argument("--quality-judge-min-source-support", default="medium", choices=["none", "weak", "medium", "strong"])
    parser.add_argument("--quality-score-threshold", type=float, default=0.7)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = _load_jsonl(args.answers_jsonl) if args.answers_jsonl else _answers_from_json(args.answers_json)
    evaluated = evaluate_student_qa_rows_quality(
        rows,
        model=args.quality_judge_model,
        max_items=args.quality_judge_max_items,
        quality_score_threshold=args.quality_score_threshold,
        min_source_support=args.quality_judge_min_source_support,
    )
    summary = {
        "answers_total": len(rows),
        "quality_summary": aggregate_quality_evals(evaluated),
        "artifacts": {
            "student_qa_quality_jsonl": str(out_dir / "student_qa_quality.jsonl"),
            "summary_json": str(out_dir / "summary.json"),
            "report_md": str(out_dir / "report.md"),
        },
    }
    _write_jsonl(evaluated, out_dir / "student_qa_quality.jsonl")
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    report = ["# Student Q&A Quality Evaluation", ""]
    report.extend(render_quality_summary_markdown(summary["quality_summary"]))
    (out_dir / "report.md").write_text("\n".join(report), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
