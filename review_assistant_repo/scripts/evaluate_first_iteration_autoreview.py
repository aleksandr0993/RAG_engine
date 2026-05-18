"""Evaluate first-iteration autoreview insertions against human-reviewed notebooks."""

# ruff: noqa: E402, I001

from __future__ import annotations

import argparse
import json
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
    return parser.parse_args()


def main() -> None:
    args = parse_args()
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
    )
    summary = payload["comparison"]["summary"]
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("candidate_auc=" + json.dumps(payload.get("candidate_auc", {}), ensure_ascii=False))
    print(f"report_md={payload['artifacts']['report_md']}")
    print(f"comparison_json={payload['artifacts']['comparison_json']}")


if __name__ == "__main__":
    main()
