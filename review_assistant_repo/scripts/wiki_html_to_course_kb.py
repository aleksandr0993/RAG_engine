#!/usr/bin/env python3
"""Convert a saved Practicum/Yandex Wiki HTML page into course KB text.

The output is intended for ``STUDENT_COURSE_KB_DIR`` and keeps only readable
assignment/course text, not the frozen Wiki JavaScript/CSS shell.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

BOILERPLATE_PREFIXES = (
    "Все сервисы",
    "Поиск",
    "Моя страница",
    "Избранное",
    "История изменений",
    "Подписки",
    "Создать страницу",
    "Уведомления",
    "Информация",
    "Связаться с нами",
    "Настройки",
    "Учётная запись",
    "Разделы",
    "О сервисе",
    "Сообщество",
    "Конфиденциально",
    "© ",
    "Infrastructure",
    "Не удалось загрузить чат",
    "Попробовать ещё раз",
    "Нет доступа к cookie",
    "Подтвердите переход",
)


def _clean_lines(raw_text: str) -> list[str]:
    lines: list[str] = []
    prev = ""
    for raw in raw_text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            continue
        if line == "#":
            continue
        if line == prev:
            continue
        if any(line.startswith(prefix) for prefix in BOILERPLATE_PREFIXES):
            continue
        lines.append(line)
        prev = line
    return lines


def _crop_to_course_content(lines: list[str]) -> list[str]:
    start_candidates = ("Проект спринта", "Что нужно сделать", "Описание проекта")
    end_candidates = (
        "Задачи спринта",
        "Учебные цели спринта",
        "ОРы спринта",
        "Содержание",
    )

    start = 0
    for marker in start_candidates:
        for i, line in enumerate(lines):
            if line.startswith(marker):
                start = i
                break
        if start:
            break

    end = len(lines)
    for i in range(start + 1, len(lines)):
        if any(lines[i].startswith(marker) for marker in end_candidates):
            end = i
            break

    return lines[start:end]


def _extract_headings(soup: BeautifulSoup) -> list[str]:
    headings: list[str] = []
    seen: set[str] = set()
    for tag in soup.find_all(["h1", "h2", "h3", "h4"]):
        text = re.sub(r"\s+", " ", tag.get_text(" ", strip=True)).strip(" #")
        if " # " in text:
            left, right = (part.strip(" #") for part in text.split(" # ", 1))
            if left == right:
                text = left
        if not text or text in seen:
            continue
        headings.append(text)
        seen.add(text)
    return headings


def convert_html(input_path: Path) -> tuple[str, dict[str, Any]]:
    soup = BeautifulSoup(input_path.read_text(encoding="utf-8"), "lxml")
    title = soup.title.get_text(" ", strip=True) if soup.title else input_path.stem
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    lines = _crop_to_course_content(_clean_lines(soup.get_text("\n")))
    headings = _extract_headings(soup)

    body = "\n".join(lines).strip()
    markdown = f"# {title}\n\n{body}\n"
    metadata = {
        "title": title,
        "source_file": str(input_path),
        "headings": headings,
        "line_count": len(lines),
        "char_count": len(body),
    }
    return markdown, metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_html", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/course_kb/wiki-python-basics.md"),
        help="Markdown/TXT output path under STUDENT_COURSE_KB_DIR.",
    )
    parser.add_argument(
        "--metadata-json",
        type=Path,
        default=None,
        help="Optional JSON metadata/section summary output.",
    )
    args = parser.parse_args()

    markdown, metadata = convert_html(args.input_html)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(markdown, encoding="utf-8")

    if args.metadata_json:
        args.metadata_json.parent.mkdir(parents=True, exist_ok=True)
        args.metadata_json.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    print(f"Wrote {args.output} ({metadata['char_count']} chars)")
    if args.metadata_json:
        print(f"Wrote {args.metadata_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
