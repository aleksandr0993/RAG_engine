#!/usr/bin/env python3
"""Import a project brief as course KB and draft review criteria.

This is a semi-automatic bootstrapper for new Practicum project types:

* converts HTML/Markdown/TXT brief to ``data/course_kb/<slug>.md``;
* writes extraction metadata next to the KB file;
* creates a draft ``configs/criteria_maps/<kind>_<slug>_v1.json``.

The generated criteria map is intentionally conservative: it uses explicit
signals from the source text and is meant to be reviewed before production use.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.wiki_html_to_course_kb import convert_html  # noqa: E402


def slugify(value: str) -> str:
    """ASCII-ish slug that is stable for filenames and criteria codes."""
    translit = {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "e",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "i",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "h",
        "ц": "c",
        "ч": "ch",
        "ш": "sh",
        "щ": "sch",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
    }
    chars: list[str] = []
    for ch in value.lower():
        chars.append(translit.get(ch, ch))
    raw = "".join(chars)
    raw = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    raw = re.sub(r"_+", "_", raw)
    return raw or "project_brief"


def _plain_text_to_markdown(input_path: Path) -> tuple[str, dict[str, Any]]:
    text = input_path.read_text(encoding="utf-8").strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    title = lines[0].lstrip("# ").strip() if lines else input_path.stem
    markdown = text if text.startswith("#") else f"# {title}\n\n{text}\n"
    headings = [
        re.sub(r"^#+\s*", "", line).strip()
        for line in lines
        if line.startswith("#")
    ]
    if not headings and title:
        headings = [title]
    return markdown, {
        "title": title,
        "source_file": str(input_path),
        "headings": headings,
        "line_count": len(lines),
        "char_count": len(text),
    }


def load_brief(input_path: Path) -> tuple[str, dict[str, Any]]:
    suffix = input_path.suffix.lower()
    if suffix in {".html", ".htm"}:
        return convert_html(input_path)
    if suffix in {".md", ".markdown", ".txt"}:
        return _plain_text_to_markdown(input_path)
    raise ValueError("input_brief must be .html, .htm, .md, .markdown, or .txt")


def extract_datasets(text: str) -> list[str]:
    matches = re.findall(r"(?:/datasets/)?[A-Za-z0-9_./-]+\.(?:csv|tsv|xlsx|xls|json)", text)
    out: list[str] = []
    seen: set[str] = set()
    for raw in matches:
        item = raw.strip(".,;:()[]{}")
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def extract_year_bounds(text: str) -> tuple[int, int] | None:
    matches = re.findall(r"(19\d{2}|20\d{2})\D{0,40}(19\d{2}|20\d{2})", text)
    for a_raw, b_raw in matches:
        a, b = int(a_raw), int(b_raw)
        if a < b and 1990 <= a <= 2050 and 1990 <= b <= 2050:
            return a, b
    return None


def extract_requirements(text: str) -> list[str]:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    requirements: list[str] = []
    markers = (
        "нужно",
        "необходимо",
        "загруз",
        "познаком",
        "проверь",
        "посчитай",
        "сделайте вывод",
        "отберите",
        "категориз",
        "выдел",
        "приведите",
        "обработ",
    )
    seen: set[str] = set()
    for line in lines:
        if len(line) < 18 or len(line) > 300:
            continue
        lower = line.lower()
        if not any(marker in lower for marker in markers):
            continue
        if line in seen:
            continue
        seen.add(line)
        requirements.append(line)
    return requirements[:40]


def _criterion(
    *,
    code: str,
    category: str,
    severity: str,
    title: str,
    description: str,
    detection_mode: str = "rule",
    rule: dict[str, Any] | None = None,
    hybrid_task: str | None = None,
    fail: str,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "code": code,
        "category": category,
        "applies_to": "ipynb",
        "severity": severity,
        "title": title,
        "description": description,
        "detection_mode": detection_mode,
        "comment_templates": {
            "pass": f"{title} — найдено.",
            "fail": fail,
        },
    }
    if detection_mode == "hybrid":
        item["hybrid_check"] = {"task": hybrid_task or "has_markdown_conclusion"}
    else:
        item["rule"] = rule or {}
    return item


def build_draft_criteria(slug: str, text: str, *, kind: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    lower = text.lower()
    datasets = extract_datasets(text)
    year_bounds = extract_year_bounds(text)
    requirements = extract_requirements(text)

    criteria: list[dict[str, Any]] = [
        _criterion(
            code=f"{slug}_intro",
            category="structure",
            severity="required",
            title="Есть введение и цель проекта",
            description="В проекте должна быть обозначена цель исследования и контекст задания.",
            detection_mode="hybrid",
            hybrid_task="has_meaningful_intro",
            fail="Добавь введение: цель проекта, контекст данных и ожидаемый результат.",
        )
    ]

    if kind == "ipynb" and datasets:
        dataset = datasets[0]
        basename = Path(dataset).name
        reader = "read_excel" if basename.endswith((".xlsx", ".xls")) else "read_csv"
        criteria.append(
            _criterion(
                code=f"{slug}_dataset_loaded",
                category="data_loading",
                severity="required",
                title=f"Загружен датасет {basename}",
                description=f"Проект должен загрузить исходный датасет {dataset}.",
                rule={
                    "artifact_types": ["code_cell"],
                    "patterns_all": [reader, basename],
                },
                fail=f"Загрузи исходный датасет {dataset} и явно покажи этот шаг в коде.",
            )
        )

    if "head()" in lower or "info()" in lower or "первые строки" in lower:
        criteria.append(
            _criterion(
                code=f"{slug}_initial_overview",
                category="data_loading",
                severity="required",
                title="Есть первичное знакомство с данными",
                description="Нужно вывести первые строки и общую информацию о датафрейме.",
                rule={
                    "artifact_types": ["code_cell"],
                    "patterns_all": [".head(", ".info("],
                },
                fail="Добавь первичный обзор данных: head() и info().",
            )
        )

    if "snake case" in lower or "snake_case" in lower:
        criteria.append(
            _criterion(
                code=f"{slug}_columns_snake_case",
                category="data_quality",
                severity="required",
                title="Названия столбцов приведены к snake_case",
                description="Названия столбцов должны быть удобны для работы в коде.",
                rule={
                    "artifact_types": ["code_cell"],
                    "patterns_all": [".columns", ".str.lower", "str.replace"],
                },
                fail="Приведи названия столбцов к snake_case.",
            )
        )

    if "пропуск" in lower:
        criteria.append(
            _criterion(
                code=f"{slug}_missing_values_quantified",
                category="data_quality",
                severity="required",
                title="Пропуски посчитаны и проанализированы",
                description="Нужно найти пропуски и объяснить решение по их обработке.",
                rule={
                    "artifact_types": ["code_cell", "markdown_cell"],
                    "patterns_any": [".isna().sum", ".isnull().sum", ".isna().mean", "пропуск"],
                    "min_normalized_length": 20,
                },
                fail="Посчитай пропуски и добавь пояснение, что с ними делаешь и почему.",
            )
        )

    if "дубликат" in lower:
        criteria.append(
            _criterion(
                code=f"{slug}_duplicates_checked",
                category="data_quality",
                severity="required",
                title="Проверены дубликаты",
                description="Нужно проверить явные и, если требуется, неявные дубликаты.",
                rule={
                    "artifact_types": ["code_cell"],
                    "patterns_any": [".duplicated(", "drop_duplicates(", ".unique(", ".value_counts("],
                },
                fail="Проверь явные и неявные дубликаты и опиши результат обработки.",
            )
        )

    if year_bounds:
        start, end = year_bounds
        criteria.append(
            _criterion(
                code=f"{slug}_period_filter",
                category="transformation",
                severity="required",
                title=f"Сформирован срез за {start}-{end}",
                description=f"Нужно отобрать данные за период {start}-{end} включительно.",
                rule={
                    "artifact_types": ["code_cell"],
                    "patterns_all": [str(start), str(end)],
                },
                fail=f"Отфильтруй данные за период {start}-{end} включительно и сохрани отдельный срез.",
            )
        )

    if "категор" in lower:
        criteria.append(
            _criterion(
                code=f"{slug}_categories_created",
                category="transformation",
                severity="required",
                title="Созданы требуемые категории",
                description="Нужно выполнить категоризацию, описанную в задании.",
                rule={
                    "artifact_types": ["code_cell", "markdown_cell"],
                    "patterns_any": ["категор", "высок", "средн", "низк", "category"],
                    "min_normalized_length": 20,
                },
                fail="Добавь категоризацию по правилам из задания и подпиши получившиеся категории.",
            )
        )

    top_match = re.search(r"топ[-\s]?(\d+)|top[-\s]?(\d+)", lower)
    if top_match:
        n = top_match.group(1) or top_match.group(2)
        criteria.append(
            _criterion(
                code=f"{slug}_top_{n}",
                category="analysis",
                severity="required",
                title=f"Выделен топ-{n}",
                description=f"Нужно выделить топ-{n} объектов по условию задания.",
                rule={
                    "artifact_types": ["code_cell"],
                    "patterns_any": [f"head({n}", f"nlargest({n}", f".head({n}", "value_counts"],
                },
                fail=f"Выдели топ-{n} по условию задания и покажи результат.",
            )
        )

    if "вывод" in lower or "интерпретац" in lower:
        criteria.append(
            _criterion(
                code=f"{slug}_final_conclusion",
                category="analysis",
                severity="warning",
                title="Есть финальный вывод",
                description="В конце проекта нужен содержательный вывод.",
                detection_mode="hybrid",
                hybrid_task="has_markdown_conclusion",
                fail="Добавь финальный вывод по результатам проекта.",
            )
        )

    return criteria, {
        "datasets": datasets,
        "year_bounds": list(year_bounds) if year_bounds else None,
        "requirements": requirements,
        "draft_note": "Criteria are generated from explicit brief signals and require human review.",
    }


def write_text(path: Path, text: str, *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"{path} already exists; pass --overwrite to replace it")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, payload: dict[str, Any], *, overwrite: bool) -> None:
    write_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        overwrite=overwrite,
    )


def import_project_brief(
    input_brief: Path,
    *,
    slug: str | None,
    kind: str,
    title: str | None,
    course_kb_dir: Path,
    criteria_dir: Path,
    overwrite: bool,
) -> dict[str, Any]:
    markdown, source_meta = load_brief(input_brief)
    resolved_title = title or str(source_meta.get("title") or input_brief.stem)
    project_slug = slugify(slug or resolved_title)
    criteria_map_code = f"{kind}_{project_slug}_v1"

    # Keep an explicit title even when caller overrides it.
    if title:
        markdown = re.sub(r"^# .+?$", f"# {title}", markdown, count=1, flags=re.MULTILINE)

    kb_path = course_kb_dir / f"{project_slug}.md"
    meta_path = course_kb_dir / f"{project_slug}.meta.json"
    criteria_path = criteria_dir / f"{criteria_map_code}.json"

    criteria, extraction = build_draft_criteria(project_slug, markdown, kind=kind)
    metadata = {
        **source_meta,
        "title": resolved_title,
        "slug": project_slug,
        "kind": kind,
        "criteria_map_code": criteria_map_code,
        "course_kb_path": str(kb_path),
        "criteria_map_path": str(criteria_path),
        "extraction": extraction,
    }

    write_text(kb_path, markdown, overwrite=overwrite)
    write_json(meta_path, metadata, overwrite=overwrite)
    write_json(criteria_path, {"criteria": criteria}, overwrite=overwrite)

    return {
        "slug": project_slug,
        "criteria_map_code": criteria_map_code,
        "course_kb_path": str(kb_path),
        "metadata_path": str(meta_path),
        "criteria_map_path": str(criteria_path),
        "criteria_count": len(criteria),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_brief", type=Path)
    parser.add_argument("--slug", default=None, help="Stable project slug, e.g. games_preprocessing")
    parser.add_argument("--kind", default="ipynb", choices=["ipynb"], help="Student submission kind")
    parser.add_argument("--title", default=None, help="Override document title")
    parser.add_argument("--course-kb-dir", type=Path, default=Path("data/course_kb"))
    parser.add_argument("--criteria-dir", type=Path, default=Path("configs/criteria_maps"))
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    try:
        result = import_project_brief(
            args.input_brief,
            slug=args.slug,
            kind=args.kind,
            title=args.title,
            course_kb_dir=args.course_kb_dir,
            criteria_dir=args.criteria_dir,
            overwrite=args.overwrite,
        )
    except Exception as exc:
        print(f"import_project_brief failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
