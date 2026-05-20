"""Evaluate first-iteration autoreview insertions against human-reviewed notebooks."""

# ruff: noqa: E402, I001

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.evaluation.first_iteration_autoreview import evaluate_first_iteration


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviewed", type=Path, required=True, help="Original human-reviewed .ipynb.")
    parser.add_argument("--restored", type=Path, required=True, help="Restored student-source .ipynb.")
    parser.add_argument("--project", default="python_preprocessing", help="Project/training slug.")
    parser.add_argument("--criteria-map", default="notebook_games_preprocessing_v1", help="Criteria map code.")
    parser.add_argument("--out-dir", type=Path, required=True, help="Directory for evaluation artifacts.")
    parser.add_argument(
        "--reviewer-insertions-path",
        type=Path,
        default=Path("data/reviewer_insertions/python_preprocessing.jsonl"),
        help="Optional learned insertion memory JSONL.",
    )
    parser.add_argument(
        "--no-memory-candidates",
        action="store_true",
        help="Disable first-iteration success/praise/actionable candidates retrieved from reviewer memory.",
    )
    parser.add_argument("--memory-candidate-min-score", type=float, default=0.35)
    parser.add_argument("--max-memory-candidates", type=int, default=30)
    parser.add_argument("--enable-llm-judge", action="store_true", help="Use LLM to keep/drop selected memory candidates.")
    parser.add_argument("--enable-llm-generator", action="store_true", help="Use LLM to adapt selected memory comments.")
    parser.add_argument(
        "--enable-llm-classifier",
        action="store_true",
        help="Use LLM to classify selected memory comments by kind, criterion/praise code, and alert color.",
    )
    parser.add_argument(
        "--enable-llm-anchor-validator",
        action="store_true",
        help="Use LLM to validate that selected memory comments belong near their proposed anchors.",
    )
    parser.add_argument("--llm-max-candidates", type=int, default=30, help="Maximum selected memory candidates sent to LLM.")
    parser.add_argument("--enable-notebook-memory", action="store_true", help="Build one notebook-wide LLM memory before judge/generator calls.")
    parser.add_argument("--notebook-memory-model", default=None, help="Optional model override for notebook memory.")
    parser.add_argument("--notebook-memory-max-input-chars", type=int, default=None)
    parser.add_argument("--notebook-memory-max-output-tokens", type=int, default=None)
    parser.add_argument(
        "--decision-threshold",
        type=float,
        default=0.5,
        help="Fixed keep_score threshold for candidate precision/recall/F1 reporting.",
    )
    parser.add_argument(
        "--candidate-score-field",
        default=None,
        help="Optional candidate score field to use instead of keep_score/confidence for ROC-AUC/F1.",
    )
    parser.add_argument("--enable-quality-judge", action="store_true", help="Run offline LLM rubric judge for review quality metrics.")
    parser.add_argument("--quality-judge-model", default=None, help="Optional model override for the quality judge.")
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
    payload = evaluate_first_iteration(
        reviewed_notebook=args.reviewed,
        restored_notebook=args.restored,
        project=args.project,
        criteria_map=args.criteria_map,
        out_dir=args.out_dir,
        reviewer_insertions_path=args.reviewer_insertions_path if args.reviewer_insertions_path else None,
        include_memory_candidates=not args.no_memory_candidates,
        memory_candidate_min_score=args.memory_candidate_min_score,
        max_memory_candidates=args.max_memory_candidates,
        enable_llm_judge=args.enable_llm_judge,
        enable_llm_generator=args.enable_llm_generator,
        enable_llm_classifier=args.enable_llm_classifier,
        enable_llm_anchor_validator=args.enable_llm_anchor_validator,
        llm_max_candidates=args.llm_max_candidates,
        decision_threshold=args.decision_threshold,
        candidate_score_field=args.candidate_score_field,
        enable_quality_judge=args.enable_quality_judge,
        quality_judge_model=args.quality_judge_model,
        quality_judge_max_items=args.quality_judge_max_items,
        quality_judge_min_source_support=args.quality_judge_min_source_support,
        quality_score_threshold=args.quality_score_threshold,
    )
    summary = payload["comparison"]["summary"]
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("candidate_auc=" + json.dumps(payload.get("candidate_auc", {}), ensure_ascii=False))
    if payload.get("quality_summary"):
        print("quality_summary=" + json.dumps(payload["quality_summary"], ensure_ascii=False))
    print(f"report_md={payload['artifacts']['report_md']}")
    print(f"comparison_json={payload['artifacts']['comparison_json']}")


if __name__ == "__main__":
    main()
