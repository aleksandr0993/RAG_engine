#!/usr/bin/env python3
"""Строит pred.jsonl для отладки evaluate: копирует эталонный assistant JSON (верхняя граница метрик)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from homework_reviewer_llm.schema import NormalizedRecord  # noqa: E402
from homework_reviewer_llm.sft_format import (  # noqa: E402
    gold_review_to_output_simple,
    gold_review_to_output_v2,
)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--gold-jsonl", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--output-format", choices=("v1", "v2"), default="v1")
    args = p.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.gold_jsonl.open(encoding="utf-8") as fin, args.output.open("w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            rec = NormalizedRecord.model_validate_json(line)
            if args.output_format == "v2":
                gold = gold_review_to_output_v2(rec)
            else:
                gold = gold_review_to_output_simple(rec)
            fout.write(
                json.dumps(
                    {"id": rec.id, "raw": gold.model_dump_json(exclude_none=True)},
                    ensure_ascii=False,
                )
                + "\n"
            )
    print("Wrote", args.output)


if __name__ == "__main__":
    main()
