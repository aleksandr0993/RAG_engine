#!/usr/bin/env python3
"""
Локальные шаги плана после сырых данных: raw (CSV или JSONL) → processed → SFT JSONL.

Обучение QLoRA не запускает — только подготовка файлов для облака.

Пример:
  python scripts/pipeline_local.py --csv reviewers.csv --workdir runs/exp01 --output-format v2
  python scripts/pipeline_local.py --raw-jsonl data/samples/raw_homework.jsonl --workdir runs/demo --output-format v2 --with-contrastive
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def run(cmd: list[str], *, cwd: Path) -> None:
    print("+", " ".join(cmd), file=sys.stderr)
    subprocess.run(cmd, check=True, cwd=str(cwd))


def merge_jsonl(dest: Path, sources: list[Path]) -> None:
    with dest.open("w", encoding="utf-8") as out:
        for src in sources:
            for line in src.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    out.write(line + "\n")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv", type=Path, help="Таблица ревьюера → конвертация в raw.jsonl")
    src.add_argument("--raw-jsonl", type=Path, dest="raw_jsonl", help="Уже готовый JSONL RawHomeworkRecord")
    p.add_argument("--workdir", required=True, type=Path, help="Каталог артефактов (создаётся)")
    p.add_argument("--seed", default="pipeline-local")
    p.add_argument("--output-format", choices=("v1", "v2"), default="v2")
    p.add_argument("--train-ratio", type=float, default=0.8)
    p.add_argument("--val-ratio", type=float, default=0.1)
    p.add_argument("--test-ratio", type=float, default=0.1)
    p.add_argument(
        "--split-mode",
        choices=("student", "strict_both"),
        default="student",
    )
    p.add_argument("--test-assignment-pool-ratio", type=float, default=0.35)
    p.add_argument("--holdout-assignments-ratio", type=float, default=0.0)
    p.add_argument(
        "--with-contrastive",
        action="store_true",
        help="Добавить контрастные SFT-примеры и файл train_val_*_plus_contrastive.jsonl",
    )
    args = p.parse_args()

    workdir = args.workdir.resolve()
    workdir.mkdir(parents=True, exist_ok=True)

    if args.csv is not None:
        raw_path = workdir / "raw.jsonl"
        run(
            [
                sys.executable,
                str(SCRIPTS / "csv_to_raw_jsonl.py"),
                "--input",
                str(args.csv.resolve()),
                "--output",
                str(raw_path),
            ],
            cwd=ROOT,
        )
    else:
        raw_path = args.raw_jsonl.resolve()
        if not raw_path.is_file():
            raise SystemExit(f"Нет файла: {raw_path}")

    processed = workdir / "processed"
    ds_cmd = [
        sys.executable,
        str(SCRIPTS / "build_dataset.py"),
        "--input",
        str(raw_path),
        "--output-dir",
        str(processed),
        "--seed",
        args.seed,
        "--train-ratio",
        str(args.train_ratio),
        "--val-ratio",
        str(args.val_ratio),
        "--test-ratio",
        str(args.test_ratio),
        "--split-mode",
        args.split_mode,
        "--holdout-assignments-ratio",
        str(args.holdout_assignments_ratio),
    ]
    if args.split_mode == "strict_both":
        ds_cmd.extend(
            [
                "--test-assignment-pool-ratio",
                str(args.test_assignment_pool_ratio),
            ]
        )
    run(ds_cmd, cwd=ROOT)

    sft_dir = workdir / "sft"
    sft_dir.mkdir(parents=True, exist_ok=True)
    sft_out = sft_dir / f"train_val_{args.output_format}.jsonl"

    train_p = processed / "train.jsonl"
    val_p = processed / "val.jsonl"
    if not train_p.is_file():
        raise SystemExit(f"Не создан {train_p} — проверьте входные данные")

    sft_cmd = [
        sys.executable,
        str(SCRIPTS / "build_sft_jsonl.py"),
        "--train",
        str(train_p),
        "--output",
        str(sft_out),
        "--output-format",
        args.output_format,
        "--splits",
        "train",
    ]
    if val_p.is_file():
        sft_cmd.extend(["--val", str(val_p), "--splits", "train,val"])
    run(sft_cmd, cwd=ROOT)

    merged_path: Path | None = None
    if args.with_contrastive:
        contrastive_p = sft_dir / f"contrastive_{args.output_format}.jsonl"
        run(
            [
                sys.executable,
                str(SCRIPTS / "build_contrastive_sft_jsonl.py"),
                "--input-jsonl",
                str(train_p),
                "--output-jsonl",
                str(contrastive_p),
                "--output-format",
                args.output_format,
            ],
            cwd=ROOT,
        )
        merged_path = sft_dir / f"train_val_{args.output_format}_plus_contrastive.jsonl"
        merge_jsonl(merged_path, [sft_out, contrastive_p])

    print("Готово:", file=sys.stderr)
    print(f"  raw:        {raw_path}", file=sys.stderr)
    print(f"  processed:  {processed}/", file=sys.stderr)
    print(f"  sft:        {sft_out}", file=sys.stderr)
    if merged_path is not None:
        print(f"  sft+contr:  {merged_path}", file=sys.stderr)
    print(
        "Далее: python scripts/print_train_command.py --workdir "
        f"{workdir} --format {args.output_format}",
        file=sys.stderr,
    )
    print(
        "Проверка метрик (oracle, без модели): python scripts/sanity_eval_workdir.py "
        f"--workdir {workdir} --format {args.output_format}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
