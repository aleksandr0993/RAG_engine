#!/usr/bin/env python3
"""Печатает готовую команду accelerate для QLoRA по артефактам pipeline_local."""

from __future__ import annotations

import argparse
import shlex
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workdir", required=True, type=Path)
    p.add_argument("--format", choices=("v1", "v2"), default="v2", dest="fmt")
    p.add_argument(
        "--dataset",
        choices=("base", "plus_contrastive"),
        default="base",
        help="base: train_val_{fmt}.jsonl; plus_contrastive: *_plus_contrastive.jsonl",
    )
    p.add_argument("--model_name", default="Qwen/Qwen2.5-7B-Instruct")
    p.add_argument("--max_steps", type=int, default=500)
    p.add_argument("--output_dir", type=str, default=None, help="По умолчанию workdir/qlora")
    args = p.parse_args()

    wd = args.workdir.resolve()
    if args.dataset == "plus_contrastive":
        ds = wd / "sft" / f"train_val_{args.fmt}_plus_contrastive.jsonl"
    else:
        ds = wd / "sft" / f"train_val_{args.fmt}.jsonl"
    if not ds.is_file():
        raise SystemExit(f"Нет датасета: {ds}")

    out = args.output_dir or str(wd / "qlora")

    train_py = shlex.quote(str(ROOT / "training" / "train_qlora.py"))
    cmd = (
        f"accelerate launch {train_py} \\\n"
        f"  --model_name {shlex.quote(args.model_name)} \\\n"
        f"  --dataset_jsonl {shlex.quote(str(ds))} \\\n"
        f"  --output_dir {shlex.quote(str(out))} \\\n"
        f"  --max_steps {args.max_steps}"
    )
    print(cmd)


if __name__ == "__main__":
    main()
