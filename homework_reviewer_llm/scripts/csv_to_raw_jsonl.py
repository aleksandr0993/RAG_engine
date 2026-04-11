#!/usr/bin/env python3
"""
Таблица от ревьюера (CSV) → raw JSONL для build_dataset.py.

Рекомендация: сохранять из Excel/Sheets как «CSV UTF-8».
Многострочный текст в ячейках в CSV поддерживается (поля в кавычках).

Обязательные колонки: id, student_id, assignment_id, submission_text, review_text, overall_score
Опциональные: task_type, language, reviewer_id, assignment_prompt, rubric_text,
               revision_history, student_profile, rubric_scores, extra

Колонка rubric_scores — один JSON-объект в одной строке, например: {"sql":8,"style":7}
Колонка extra — JSON-объект (обычно пусто {}).
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from homework_reviewer_llm.raw_csv import REQUIRED, row_to_record_dict  # noqa: E402
from homework_reviewer_llm.schema import RawHomeworkRecord  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", required=True, type=Path, help="CSV с заголовком колонок")
    p.add_argument("--output", required=True, type=Path, help="Выходной raw.jsonl")
    p.add_argument(
        "--encoding",
        default="utf-8-sig",
        help="utf-8-sig удобен для Excel; для простого UTF-8 укажите utf-8",
    )
    p.add_argument("--delimiter", default=",", help="Разделитель полей")
    args = p.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    n_ok = 0
    with args.input.open(encoding=args.encoding, newline="") as fin, args.output.open(
        "w", encoding="utf-8"
    ) as fout:
        reader = csv.DictReader(fin, delimiter=args.delimiter)
        if reader.fieldnames is None:
            raise SystemExit("CSV без заголовка")
        missing = [c for c in REQUIRED if c not in reader.fieldnames]
        if missing:
            raise SystemExit(f"В заголовке нет колонок: {missing}. Есть: {reader.fieldnames}")

        for lineno, row in enumerate(reader, start=2):
            if not any(row.get(k) and str(row.get(k)).strip() for k in REQUIRED):
                continue
            try:
                data = row_to_record_dict(row)
                rec = RawHomeworkRecord.model_validate(data)
            except Exception as e:
                raise SystemExit(f"Строка {lineno}: {e}") from e
            fout.write(rec.model_dump_json() + "\n")
            n_ok += 1

    print(f"Wrote {n_ok} records to {args.output}")


if __name__ == "__main__":
    main()
