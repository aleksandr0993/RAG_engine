#!/usr/bin/env python3
"""Сравнение эталона (из normalized JSONL) с предсказаниями модели: MAE, rubric, JSON validity."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from homework_reviewer_llm.metrics import evaluate_pairs, evaluate_pairs_v2  # noqa: E402
from homework_reviewer_llm.schema import NormalizedRecord  # noqa: E402
from homework_reviewer_llm.sft_format import (  # noqa: E402
    gold_review_to_output_simple,
    gold_review_to_output_v2,
)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--gold-jsonl", required=True, type=Path, help="test.jsonl или hard.jsonl (normalized)")
    p.add_argument("--pred-jsonl", required=True, type=Path, help="По строке: {\"id\":..., \"raw\":...}")
    p.add_argument("--report-json", type=Path, help="Куда сохранить сводку метрик")
    p.add_argument("--format", choices=("v1", "v2"), default="v1", dest="fmt")
    args = p.parse_args()

    gold_by_id: dict[str, NormalizedRecord] = {}
    with args.gold_jsonl.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = NormalizedRecord.model_validate_json(line)
            gold_by_id[rec.id] = rec

    pred_by_id: dict[str, str] = {}
    with args.pred_jsonl.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            pred_by_id[str(obj["id"])] = obj["raw"]

    ids = sorted(set(gold_by_id) & set(pred_by_id))
    if not ids:
        raise SystemExit("Нет пересечения id между gold и pred")

    if args.fmt == "v2":
        gold_outputs = [gold_review_to_output_v2(gold_by_id[i]) for i in ids]
        metrics = evaluate_pairs_v2(gold_outputs, [pred_by_id[i] for i in ids])
    else:
        gold_outputs = [gold_review_to_output_simple(gold_by_id[i]) for i in ids]
        metrics = evaluate_pairs(gold_outputs, [pred_by_id[i] for i in ids])
    summary = metrics.summary()
    summary["n_matched"] = len(ids)
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.report_json:
        args.report_json.parent.mkdir(parents=True, exist_ok=True)
        with args.report_json.open("w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
