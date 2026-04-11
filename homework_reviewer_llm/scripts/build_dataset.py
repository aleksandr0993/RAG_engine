#!/usr/bin/env python3
"""Сырой JSONL → санитизация, фильтры, дедуп, leak-safe split → normalized JSONL."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# пакет из src
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from homework_reviewer_llm.schema import RawHomeworkRecord  # noqa: E402
from homework_reviewer_llm.sanitize import (  # noqa: E402
    dedupe_by_submission_hash,
    passes_quality_filters,
    scrub_record,
)
from homework_reviewer_llm.split import (  # noqa: E402
    leak_safe_split,
    leak_safe_split_strict_both,
    mark_hard_subset,
)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True, type=Path, help="JSONL с RawHomeworkRecord")
    p.add_argument("--output-dir", required=True, type=Path, help="Каталог для split-файлов")
    p.add_argument("--seed", default="homework-reviewer-llm")
    p.add_argument("--train-ratio", type=float, default=0.8)
    p.add_argument("--val-ratio", type=float, default=0.1)
    p.add_argument("--test-ratio", type=float, default=0.1)
    p.add_argument("--holdout-assignments-ratio", type=float, default=0.0)
    p.add_argument(
        "--split-mode",
        choices=("student", "strict_both"),
        default="student",
        help="student: утечка только по студенту + опц. holdout заданий; "
        "strict_both: раздельные пулы студентов и assignment_id",
    )
    p.add_argument(
        "--test-assignment-pool-ratio",
        type=float,
        default=0.35,
        help="Для strict_both: доля assignment_id в test-пуле",
    )
    p.add_argument("--hard-fraction", type=float, default=0.0, help="Доля test → hard")
    p.add_argument("--min-submission-len", type=int, default=50)
    p.add_argument("--min-review-len", type=int, default=20)
    args = p.parse_args()

    raw_rows: list[RawHomeworkRecord] = []
    with args.input.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            raw_rows.append(RawHomeworkRecord.model_validate_json(line))

    normalized = [scrub_record(r) for r in raw_rows]
    normalized = [r for r in normalized if passes_quality_filters(r, min_submission_len=args.min_submission_len, min_review_len=args.min_review_len)]
    normalized = dedupe_by_submission_hash(normalized)

    if args.split_mode == "student":
        normalized = leak_safe_split(
            normalized,
            seed=args.seed,
            train_ratio=args.train_ratio,
            val_ratio=args.val_ratio,
            test_ratio=args.test_ratio,
            holdout_assignments_ratio=args.holdout_assignments_ratio,
        )
    else:
        normalized, dropped = leak_safe_split_strict_both(
            normalized,
            seed=args.seed,
            train_ratio=args.train_ratio,
            val_ratio=args.val_ratio,
            test_ratio=args.test_ratio,
            test_assignment_pool_ratio=args.test_assignment_pool_ratio,
        )
        print(f"strict_both: dropped {dropped} rows (no matching student×assignment pool)")
    if args.hard_fraction > 0:
        normalized = mark_hard_subset(normalized, fraction=args.hard_fraction)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    buckets: dict[str, list] = {"train": [], "val": [], "test": [], "hard": []}
    for r in normalized:
        s = r.split or "train"
        if s not in buckets:
            buckets[s] = []
        buckets[s].append(r.model_dump(mode="json"))

    for name, rows in buckets.items():
        if not rows:
            continue
        out = args.output_dir / f"{name}.jsonl"
        with out.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"Wrote {len(rows)} rows to {out}")


if __name__ == "__main__":
    main()
