#!/usr/bin/env python3
"""
Merge several master-review .ipynb files into JSONL for runtime retrieval and optional fine-tuning export.

Usage (from review_assistant_repo root, venv activated):
  python scripts/build_review_training_corpus.py \\
    --input-dir ./data/master_reviews \\
    --project my_practicum_project \\
    --runtime-out ./data/project_training.jsonl \\
    --finetune-out ./data/finetune_review_dialogue.jsonl

Cell roles are detected via Russian markers in cell source (see app.parsers.notebook).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.retrieval.notebook_training import extract_rows_from_ipynb, merge_write_jsonl


def main() -> None:
    ap = argparse.ArgumentParser(description="Build review training JSONL from master-review notebooks.")
    ap.add_argument(
        "--input-dir",
        type=Path,
        required=True,
        help="Directory containing one or more .ipynb files",
    )
    ap.add_argument(
        "--project",
        dest="source_project",
        required=True,
        help="Stable project id / slug (stored in source_project in JSONL)",
    )
    ap.add_argument(
        "--runtime-out",
        type=Path,
        required=True,
        help="Output JSONL for ENABLE_PROJECT_REVIEW_TRAINING (reviewer + middle_reviewer rows only)",
    )
    ap.add_argument(
        "--finetune-out",
        type=Path,
        default=None,
        help="Optional JSONL with all roles (including student) for external fine-tuning",
    )
    args = ap.parse_args()

    input_dir: Path = args.input_dir
    if not input_dir.is_dir():
        raise SystemExit(f"Not a directory: {input_dir}")

    notebooks = sorted(input_dir.glob("*.ipynb"))
    if not notebooks:
        raise SystemExit(f"No .ipynb files in {input_dir}")

    runtime_all: list = []
    finetune_all: list = []
    for ipynb in notebooks:
        r, f = extract_rows_from_ipynb(ipynb, source_project=args.source_project)
        runtime_all.extend(r)
        finetune_all.extend(f)

    merge_write_jsonl(runtime_all, args.runtime_out)
    print(f"Wrote {len(runtime_all)} runtime rows -> {args.runtime_out.resolve()}")
    if args.finetune_out:
        merge_write_jsonl(finetune_all, args.finetune_out)
        print(f"Wrote {len(finetune_all)} finetune rows -> {args.finetune_out.resolve()}")


if __name__ == "__main__":
    main()
