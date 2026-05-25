"""Build a labeled keep/drop dataset for first-iteration autoreview candidates.

Input manifest is JSONL. Each row:
{
  "id": "case-001",
  "split": "train|val|test",
  "reviewed": "/path/to/human_reviewed.ipynb",
  "restored": "/path/to/restored_student.ipynb",
  "project": "python_preprocessing",
  "criteria_map": "notebook_games_preprocessing_v1",
  "reviewer_insertions_path": "/path/to/reviewer_insertions.jsonl"
}
"""

# ruff: noqa: E402, I001

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.evaluation.first_iteration_autoreview import (
    _average_precision,
    _best_f1_threshold,
    _candidate_breakdowns,
    _classification_counts,
    _rank_auc,
    evaluate_first_iteration,
)
from app.evaluation.quality_metrics import aggregate_quality_evals


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def _resolve_path(value: str | None, *, base_dir: Path) -> Path | None:
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else base_dir / path


def _points(rows: list[dict[str, Any]]) -> list[tuple[float, int]]:
    return [(float(row.get("keep_score") or 0.0), int(row.get("auc_label") or row.get("label") or 0)) for row in rows]


def _summarize(rows: list[dict[str, Any]], *, threshold: float) -> dict[str, Any]:
    points = _points(rows)
    positives = sum(label for _score, label in points)
    return {
        "candidate_total": len(rows),
        "positive_candidates": positives,
        "negative_candidates": len(rows) - positives,
        "roc_auc": _rank_auc(points),
        "pr_auc_average_precision": _average_precision(points),
        "at_threshold": _classification_counts(points, threshold),
        "breakdowns": _candidate_breakdowns(rows, decision_threshold=threshold),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs-jsonl", type=Path, required=True, help="JSONL manifest of reviewed/restored notebook pairs.")
    parser.add_argument("--out-dir", type=Path, required=True, help="Output directory for dataset and reports.")
    parser.add_argument("--default-project", default="python_preprocessing")
    parser.add_argument("--default-criteria-map", default="notebook_games_preprocessing_v1")
    parser.add_argument("--default-reviewer-insertions-path", type=Path, default=None)
    parser.add_argument("--memory-candidate-min-score", type=float, default=0.35)
    parser.add_argument("--max-memory-candidates", type=int, default=30)
    parser.add_argument("--decision-threshold", type=float, default=None, help="If omitted, choose best F1 threshold on val split.")
    parser.add_argument("--candidate-score-field", default=None)
    parser.add_argument("--enable-llm-judge", action="store_true")
    parser.add_argument("--enable-llm-generator", action="store_true")
    parser.add_argument("--enable-llm-classifier", action="store_true")
    parser.add_argument("--enable-llm-anchor-validator", action="store_true")
    parser.add_argument(
        "--llm-judge-filter-mode",
        default="balanced",
        choices=["off", "balanced", "aggressive"],
        help="Offline-only deterministic gate applied after LLM judge for memory candidates.",
    )
    parser.add_argument("--llm-max-candidates", type=int, default=30)
    parser.add_argument("--enable-notebook-memory", action="store_true")
    parser.add_argument("--notebook-memory-model", default=None)
    parser.add_argument("--notebook-memory-max-input-chars", type=int, default=None)
    parser.add_argument("--notebook-memory-max-output-tokens", type=int, default=None)
    parser.add_argument("--enable-quality-judge", action="store_true", help="Run offline LLM rubric judge for review quality metrics.")
    parser.add_argument("--quality-judge-model", default=None)
    parser.add_argument("--quality-judge-max-items", type=int, default=100)
    parser.add_argument("--quality-judge-min-source-support", default="medium", choices=["none", "weak", "medium", "strong"])
    parser.add_argument("--quality-score-threshold", type=float, default=0.7)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.enable_notebook_memory:
        os.environ["ENABLE_NOTEBOOK_MEMORY"] = "true"
    if args.notebook_memory_model:
        os.environ["NOTEBOOK_MEMORY_MODEL"] = args.notebook_memory_model
    if args.notebook_memory_max_input_chars is not None:
        os.environ["NOTEBOOK_MEMORY_MAX_INPUT_CHARS"] = str(args.notebook_memory_max_input_chars)
    if args.notebook_memory_max_output_tokens is not None:
        os.environ["NOTEBOOK_MEMORY_MAX_OUTPUT_TOKENS"] = str(args.notebook_memory_max_output_tokens)
    from app.config import get_settings

    get_settings.cache_clear()
    manifest_path = args.pairs_jsonl.resolve()
    manifest_base = manifest_path.parent
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    all_candidates: list[dict[str, Any]] = []
    pair_summaries: list[dict[str, Any]] = []
    manifest = _load_jsonl(manifest_path)
    preliminary_threshold = args.decision_threshold if args.decision_threshold is not None else 0.5

    for idx, row in enumerate(manifest, start=1):
        pair_id = str(row.get("id") or f"pair-{idx:04d}")
        split = str(row.get("split") or "unspecified")
        reviewed = _resolve_path(str(row.get("reviewed") or ""), base_dir=manifest_base)
        restored = _resolve_path(str(row.get("restored") or ""), base_dir=manifest_base)
        if reviewed is None or restored is None:
            raise ValueError(f"{pair_id}: reviewed/restored are required")
        project = str(row.get("project") or args.default_project)
        criteria_map = str(row.get("criteria_map") or args.default_criteria_map)
        reviewer_insertions_path = _resolve_path(
            str(row.get("reviewer_insertions_path") or ""),
            base_dir=manifest_base,
        ) or args.default_reviewer_insertions_path

        pair_out = out_dir / "pairs" / pair_id
        payload = evaluate_first_iteration(
            reviewed_notebook=reviewed,
            restored_notebook=restored,
            project=project,
            criteria_map=criteria_map,
            out_dir=pair_out,
            reviewer_insertions_path=reviewer_insertions_path,
            include_memory_candidates=True,
            memory_candidate_min_score=args.memory_candidate_min_score,
            max_memory_candidates=args.max_memory_candidates,
            enable_llm_judge=args.enable_llm_judge,
            enable_llm_generator=args.enable_llm_generator,
            enable_llm_classifier=args.enable_llm_classifier,
            enable_llm_anchor_validator=args.enable_llm_anchor_validator,
            llm_judge_filter_mode=args.llm_judge_filter_mode,
            llm_max_candidates=args.llm_max_candidates,
            decision_threshold=preliminary_threshold,
            candidate_score_field=args.candidate_score_field,
            enable_quality_judge=args.enable_quality_judge,
            quality_judge_model=args.quality_judge_model,
            quality_judge_max_items=args.quality_judge_max_items,
            quality_judge_min_source_support=args.quality_judge_min_source_support,
            quality_score_threshold=args.quality_score_threshold,
        )
        pair_candidates = _load_jsonl(Path(payload["artifacts"]["all_memory_candidates_labeled_jsonl"]))
        for candidate in pair_candidates:
            candidate["pair_id"] = pair_id
            candidate["split"] = split
            candidate["reviewed_notebook"] = str(reviewed)
            candidate["restored_notebook"] = str(restored)
            candidate["criteria_map"] = criteria_map
            candidate["project"] = project
            all_candidates.append(candidate)
        pair_summaries.append(
            {
                "pair_id": pair_id,
                "split": split,
                "project": project,
                "criteria_map": criteria_map,
                "candidate_total": len(pair_candidates),
                "candidate_auc": payload.get("candidate_auc") or {},
                "comparison_summary": (payload.get("comparison") or {}).get("summary") or {},
                "report_md": payload["artifacts"]["report_md"],
            }
        )

    val_rows = [row for row in all_candidates if row.get("split") == "val"]
    if args.decision_threshold is None:
        threshold_source = "val" if val_rows else "default_no_val_split"
        selected = _best_f1_threshold(_points(val_rows)) if val_rows else _classification_counts([], 0.5)
        decision_threshold = float(selected["threshold"])
    else:
        threshold_source = "provided"
        decision_threshold = float(args.decision_threshold)

    split_metrics = {
        split: _summarize([row for row in all_candidates if row.get("split") == split], threshold=decision_threshold)
        for split in sorted({str(row.get("split") or "unspecified") for row in all_candidates})
    }
    summary = {
        "pairs_total": len(manifest),
        "candidate_total": len(all_candidates),
        "decision_threshold": decision_threshold,
        "threshold_source": threshold_source,
        "overall": _summarize(all_candidates, threshold=decision_threshold),
        "by_split": split_metrics,
        "pairs": pair_summaries,
        "artifacts": {
            "candidates_labeled_jsonl": str(out_dir / "candidates_labeled.jsonl"),
            "summary_json": str(out_dir / "summary.json"),
        },
    }
    if args.enable_quality_judge:
        summary["quality_summary"] = aggregate_quality_evals(all_candidates)

    _write_jsonl(all_candidates, out_dir / "candidates_labeled.jsonl")
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
