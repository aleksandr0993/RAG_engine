#!/usr/bin/env python3
"""Добавляет контрастные SFT-примеры (плохой JSON → хороший / inline warning)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from homework_reviewer_llm.contrastive import (  # noqa: E402
    contrastive_record_to_dict,
    parse_contrastive_kinds,
)
from homework_reviewer_llm.schema import NormalizedRecord  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input-jsonl", required=True, type=Path, help="train.jsonl (или другой normalized)")
    p.add_argument("--output-jsonl", required=True, type=Path)
    p.add_argument(
        "--modes",
        default="rewrite_bad,inline_warning",
        help="Через запятую: rewrite_bad, inline_warning",
    )
    p.add_argument(
        "--kinds",
        default="too_soft,no_justification,vague_recommendations",
        help="Через запятую: too_soft, no_justification, vague_recommendations",
    )
    p.add_argument(
        "--splits-allow",
        default="train,val",
        help="Для каких split из строки записи добавлять примеры (через запятую)",
    )
    p.add_argument(
        "--output-format",
        choices=("v1", "v2"),
        default="v1",
    )
    args = p.parse_args()

    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    for m in modes:
        if m not in ("rewrite_bad", "inline_warning"):
            raise SystemExit(f"unknown mode: {m}")

    kinds = parse_contrastive_kinds(args.kinds)
    if not kinds:
        raise SystemExit("укажите хотя бы один kind")

    allow = {s.strip() for s in args.splits_allow.split(",") if s.strip()}

    args.output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with args.input_jsonl.open(encoding="utf-8") as fin, args.output_jsonl.open(
        "w", encoding="utf-8"
    ) as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            rec = NormalizedRecord.model_validate_json(line)
            sp = rec.split or "train"
            if sp not in allow:
                continue
            for mode in modes:
                for kind in kinds:
                    obj = contrastive_record_to_dict(
                        rec, mode=mode, kind=kind, output_format=args.output_format
                    )
                    fout.write(json.dumps(obj, ensure_ascii=False) + "\n")
                    n += 1
    print(f"Wrote {n} contrastive SFT rows to {args.output_jsonl}")


if __name__ == "__main__":
    main()
