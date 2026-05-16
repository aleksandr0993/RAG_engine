"""Extract senior-reviewer guidance from author solution notebooks.

Author notebooks for Practicum projects often contain color-coded reviewer
guidance blocks rather than regular ``Комментарий ревьюера`` cells. This module
turns those blocks into two useful artefacts:

* structured rubric JSON / Markdown for human review;
* JSONL rows compatible with project-training retrieval.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import nbformat
from bs4 import BeautifulSoup

COLOR_POLICY: dict[str, dict[str, str]] = {
    "#3c763d": {
        "alert_color": "success",
        "level": "pass",
        "label_ru": "хорошее выполнение",
    },
    "#8a6d3b": {
        "alert_color": "warning",
        "level": "recommendation",
        "label_ru": "зачёт с рекомендацией",
    },
    "#a94442": {
        "alert_color": "danger",
        "level": "required_fix",
        "label_ru": "обязательная правка",
    },
    "#31708f": {
        "alert_color": "info",
        "level": "author_note",
        "label_ru": "методическая заметка",
    },
}

_FONT_COLOR_RE = re.compile(r"<font\s+color=['\"](?P<color>#[0-9a-fA-F]{6})['\"]>(?P<body>.*)", re.I)
_BULLET_RE = re.compile(r"^\s*>?\s*-\s*(?P<body>.*)$")
_MARKER_AUTHOR = "Комментарий автора"
_MARKER_CRITERIA = "Критерии проверки"


@dataclass
class SeniorRubricItem:
    color: str
    alert_color: str
    level: str
    label_ru: str
    text: str


@dataclass
class SeniorRubricBlock:
    cell_idx: int
    block_type: str
    section_name: str
    criterion_codes: list[str]
    intro_text: str = ""
    items: list[SeniorRubricItem] = field(default_factory=list)
    raw_text: str = ""


def _cell_source(cell: Any) -> str:
    src = cell.get("source", "")
    if isinstance(src, list):
        return "".join(src)
    return str(src or "")


def clean_markup(text: str) -> str:
    text = text.replace("</font>", "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
    text = re.sub(r"^[>\s-]+", "", text)
    text = re.sub(r"^(👍|📝|✍|🧙‍♂|🧙‍♂️|🕵️♂️|🕵️♂)\s*", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _heading_text(source: str) -> str | None:
    for line in source.splitlines():
        if line.startswith("#"):
            text = re.sub(r"^#+\s*", "", line).strip()
            if text:
                return text
    return None


def _infer_criterion_codes(section_name: str, text: str) -> list[str]:
    hay = f"{section_name}\n{text}".lower()
    codes: list[str] = []
    if any(token in hay for token in ["вводн", "цели", "содержимое проекта", "оглавл"]):
        codes.append("games_project_intro")
    if any(token in hay for token in ["знакомство", ".head", ".info", "корректности данных"]):
        codes.extend(["games_dataset_loaded", "games_initial_overview", "games_overview_commentary"])
    if any(token in hay for token in ["названия", "столбц", "snake_case", "snake case"]):
        codes.append("games_columns_snake_case")
    if any(token in hay for token in ["типы данных", "pd.to_numeric", "user_score", "eu_sales", "jp_sales"]):
        codes.append("games_scores_numeric_conversion")
    if any(token in hay for token in ["количество пропуск", "абсолют", "относитель"]):
        codes.append("games_missing_values_quantified")
    if any(token in hay for token in ["обработк", "fillna", "индикатор", "пропуски были изучены"]):
        codes.append("games_missing_values_decision")
    if any(token in hay for token in ["дубликат", "genre", "жанр"]):
        codes.extend(["games_genre_normalized", "games_duplicates_checked"])
    if any(token in hay for token in ["удал", "отфильтрован", "доля", "процент"]):
        codes.append("games_removed_rows_quantified")
    if "2000" in hay and "2013" in hay:
        codes.append("games_actual_period_filter")
    if any(token in hay for token in ["категоризац", "категоризация", "оценк"]):
        codes.append("games_score_categories")
    if any(token in hay for token in ["топ-7", "топ 7", "top-7", "top 7"]):
        codes.append("games_top7_platforms")
    if "итоговый вывод" in hay or "финальн" in hay:
        codes.append("games_final_conclusion")
    out: list[str] = []
    seen: set[str] = set()
    for code in codes:
        if code not in seen:
            seen.add(code)
            out.append(code)
    return out or ["games_project_general"]


def _parse_color_bullet(line: str) -> SeniorRubricItem | None:
    bullet = _BULLET_RE.match(line)
    if not bullet:
        return None
    body = bullet.group("body").strip()
    m = _FONT_COLOR_RE.search(body)
    if not m:
        return None
    color = m.group("color").lower()
    policy = COLOR_POLICY.get(color)
    if not policy:
        return None
    text = clean_markup(m.group("body"))
    if not text:
        return None
    return SeniorRubricItem(
        color=color,
        alert_color=policy["alert_color"],
        level=policy["level"],
        label_ru=policy["label_ru"],
        text=text,
    )


def parse_guidance_cell(
    source: str,
    *,
    cell_idx: int,
    section_name: str,
) -> SeniorRubricBlock | None:
    if _MARKER_CRITERIA in source:
        block_type = "criteria"
    elif _MARKER_AUTHOR in source:
        block_type = "author_note"
    else:
        return None

    items: list[SeniorRubricItem] = []
    intro_lines: list[str] = []
    for line in source.splitlines():
        item = _parse_color_bullet(line)
        if item:
            items.append(item)
            continue
        if _MARKER_CRITERIA in line or _MARKER_AUTHOR in line:
            cleaned = clean_markup(line)
            cleaned = re.sub(r"^(🕵️♂️|🕵️♂|🧙‍♂|🧙‍♂️)\s*", "", cleaned).strip()
            if cleaned:
                intro_lines.append(cleaned)

    if block_type == "author_note" and not items:
        text = clean_markup(source)
        color = "#31708f"
        policy = COLOR_POLICY[color]
        items.append(
            SeniorRubricItem(
                color=color,
                alert_color=policy["alert_color"],
                level=policy["level"],
                label_ru=policy["label_ru"],
                text=text,
            )
        )

    if not items and not intro_lines:
        return None

    whole_text = "\n".join([*intro_lines, *[i.text for i in items]])
    return SeniorRubricBlock(
        cell_idx=cell_idx,
        block_type=block_type,
        section_name=section_name,
        criterion_codes=_infer_criterion_codes(section_name, whole_text),
        intro_text=" ".join(intro_lines),
        items=items,
        raw_text=source,
    )


def extract_senior_review_notebook(
    ipynb_path: Path | str,
    *,
    source_project: str,
    source_notebook: str | None = None,
) -> dict[str, Any]:
    path = Path(ipynb_path)
    nb = nbformat.read(str(path), as_version=4)
    notebook_name = source_notebook or path.name

    headings: list[dict[str, Any]] = []
    blocks: list[SeniorRubricBlock] = []
    current_section = ""
    for idx, cell in enumerate(nb.cells):
        source = _cell_source(cell)
        if cell.get("cell_type") == "markdown":
            heading = _heading_text(source)
            if heading:
                current_section = heading
                headings.append({"cell_idx": idx, "text": heading})
            block = parse_guidance_cell(source, cell_idx=idx, section_name=current_section)
            if block:
                blocks.append(block)

    rows: list[dict[str, Any]] = []
    for block in blocks:
        for item_idx, item in enumerate(block.items):
            for criterion_code in block.criterion_codes:
                rows.append(
                    {
                        "example_id": f"{source_project}_{path.stem}_{block.cell_idx}_{item_idx}_{criterion_code}",
                        "criterion_code": criterion_code,
                        "text": item.text,
                        "tags": [
                            "senior_review",
                            block.block_type,
                            f"alert_{item.alert_color}",
                            f"level_{item.level}",
                        ],
                        "score": 1.0,
                        "source_kind": "project_training",
                        "author_role": "reviewer",
                        "source_project": source_project,
                        "source_notebook": notebook_name,
                        "student_context": block.intro_text,
                        "section_name": block.section_name,
                        "alert_color": item.alert_color,
                        "rubric_level": item.level,
                        "rubric_color": item.color,
                    }
                )

    return {
        "meta": {
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{source_project}:{path.resolve()}")),
            "source_project": source_project,
            "source_notebook": notebook_name,
            "source_path": str(path),
            "headings_count": len(headings),
            "guidance_blocks_count": len(blocks),
            "runtime_rows_count": len(rows),
            "color_policy": COLOR_POLICY,
        },
        "headings": headings,
        "guidance_blocks": [
            {
                "cell_idx": b.cell_idx,
                "block_type": b.block_type,
                "section_name": b.section_name,
                "criterion_codes": b.criterion_codes,
                "intro_text": b.intro_text,
                "items": [
                    {
                        "color": i.color,
                        "alert_color": i.alert_color,
                        "level": i.level,
                        "label_ru": i.label_ru,
                        "text": i.text,
                    }
                    for i in b.items
                ],
            }
            for b in blocks
        ],
        "runtime_rows": rows,
    }


def write_runtime_jsonl(rows: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def rubric_to_markdown(payload: dict[str, Any]) -> str:
    meta = payload.get("meta") or {}
    lines = [
        f"# Senior review guidance: {meta.get('source_project', '')}",
        "",
        f"- Source notebook: `{meta.get('source_notebook', '')}`",
        f"- Guidance blocks: {meta.get('guidance_blocks_count', 0)}",
        f"- Retrieval rows: {meta.get('runtime_rows_count', 0)}",
        "",
        "Color policy:",
        "- green / `#3c763d`: good execution",
        "- yellow / `#8a6d3b`: pass with recommendation",
        "- red / `#a94442`: required fix",
        "- blue / `#31708f`: author note",
        "",
    ]
    for block in payload.get("guidance_blocks") or []:
        lines.append(f"## {block.get('section_name') or 'Без секции'}")
        lines.append("")
        codes = ", ".join(f"`{c}`" for c in block.get("criterion_codes") or [])
        lines.append(f"Criteria codes: {codes}")
        if block.get("intro_text"):
            lines.append("")
            lines.append(str(block["intro_text"]))
        lines.append("")
        for item in block.get("items") or []:
            lines.append(
                f"- **{item.get('label_ru')}** ({item.get('alert_color')}, {item.get('color')}): "
                f"{item.get('text')}"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
