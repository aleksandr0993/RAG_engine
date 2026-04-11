#!/usr/bin/env python3
"""
Проверка конвейера метрик без модели: эталон = gold из normalized test,
предсказание = тот же gold (oracle). Ожидается score_mae≈0, json_valid_rate=1.

Использование после pipeline_local.py, когда есть workdir/processed/test.jsonl.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workdir", required=True, type=Path)
    p.add_argument("--format", choices=("v1", "v2"), default="v2", dest="fmt")
    args = p.parse_args()

    wd = args.workdir.resolve()
    test_jsonl = wd / "processed" / "test.jsonl"
    if not test_jsonl.is_file():
        raise SystemExit(f"Нет {test_jsonl}. Сначала pipeline_local.py (нужен непустой test).")

    metrics_dir = wd / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    pred = metrics_dir / "pred_oracle.jsonl"
    report = metrics_dir / f"oracle_{args.fmt}.json"

    dummy_cmd = [
        sys.executable,
        str(SCRIPTS / "make_dummy_predictions.py"),
        "--gold-jsonl",
        str(test_jsonl),
        "--output",
        str(pred),
        "--output-format",
        args.fmt,
    ]
    eval_cmd = [
        sys.executable,
        str(SCRIPTS / "evaluate.py"),
        "--gold-jsonl",
        str(test_jsonl),
        "--pred-jsonl",
        str(pred),
        "--format",
        args.fmt,
        "--report-json",
        str(report),
    ]
    print("+", " ".join(dummy_cmd), file=sys.stderr)
    subprocess.run(dummy_cmd, check=True, cwd=str(ROOT))
    print("+", " ".join(eval_cmd), file=sys.stderr)
    subprocess.run(eval_cmd, check=True, cwd=str(ROOT))
    print(f"Отчёт: {report}", file=sys.stderr)


if __name__ == "__main__":
    main()
