#!/usr/bin/env python3
"""Normalized JSONL (train/val) → JSONL с полем messages для SFT."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from homework_reviewer_llm.schema import NormalizedRecord  # noqa: E402
from homework_reviewer_llm.sft_format import record_to_sft_dict  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--train", type=Path, help="train.jsonl")
    p.add_argument("--val", type=Path, help="val.jsonl")
    p.add_argument("--output", required=True, type=Path)
    p.add_argument(
        "--output-format",
        choices=("v1", "v2"),
        default="v1",
        help="Формат эталонного assistant JSON (v1 классический или v2 гибридный)",
    )
    p.add_argument(
        "--splits",
        default="train,val",
        help="Какие split включить (через запятую), например train,val",
    )
    args = p.parse_args()

    paths: list[Path] = []
    if args.train:
        paths.append(args.train)
    if args.val:
        paths.append(args.val)
    if not paths:
        p.error("укажите --train и/или --val")

    want = {s.strip() for s in args.splits.split(",") if s.strip()}
    n = 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as out:
        for path in paths:
            split_name = path.stem
            if split_name not in want:
                continue
            with path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    rec = NormalizedRecord.model_validate_json(line)
                    obj = record_to_sft_dict(rec, output_format=args.output_format)
                    out.write(json.dumps(obj, ensure_ascii=False) + "\n")
                    n += 1
    print(f"Wrote {n} SFT examples to {args.output}")


if __name__ == "__main__":
    main()
