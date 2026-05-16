from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import nbformat

from app.parsers.notebook import infer_notebook_comment_role, is_review_role_cell

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_HEADING_RE = re.compile(r"^\s*(#{1,6})\s+(.+?)\s*$")
_ALERT_RE = re.compile(r"alert-(success|info|danger|warning)", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[\wа-яА-ЯёЁ]+", re.UNICODE)

FEATURE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("read_csv", r"read_csv|new_games\.csv"),
    ("head", r"\.head\("),
    ("info", r"\.info\("),
    ("columns", r"\.columns|columns\.values"),
    ("lower", r"\.lower\(|\.str\.lower"),
    ("replace", r"\.replace\(|str\.replace"),
    ("to_numeric", r"to_numeric"),
    ("isna_sum", r"\.isna\(\)\.sum"),
    ("isna_mean", r"\.isna\(\)\.mean"),
    ("fillna", r"fillna"),
    ("dropna", r"dropna"),
    ("duplicated", r"duplicated"),
    ("drop_duplicates", r"drop_duplicates"),
    ("groupby", r"groupby"),
    ("value_counts", r"value_counts"),
    ("head7", r"head\(7"),
    ("apply", r"\.apply\("),
    ("pd_cut", r"pd\.cut"),
    ("rating", r"\brating\b|non_rating|non rating"),
    ("genre", r"\bgenre\b"),
    ("platform", r"\bplatform\b"),
    ("year", r"year_of_release|\byear\b|2000|2013"),
    ("user_score", r"user_score"),
    ("critic_score", r"critic_score"),
    ("eu_sales", r"eu_sales"),
    ("jp_sales", r"jp_sales"),
    ("score_category", r"score_category|user_category|critic_category|categor"),
)


@dataclass(frozen=True)
class InsertionAnchor:
    position_idx: int
    score: float
    example: dict[str, Any]


def normalize_cell_source(source: Any) -> str:
    if isinstance(source, list):
        source = "".join(source)
    elif not isinstance(source, str):
        source = str(source or "")
    return _WS_RE.sub(" ", source).strip()


def plain_text(source: str) -> str:
    text = _TAG_RE.sub(" ", source)
    return _WS_RE.sub(" ", text).strip()


def content_hash(text: str) -> str:
    return "sha1:" + hashlib.sha1(text.encode("utf-8")).hexdigest()


def detect_alert_color(source: str) -> str:
    match = _ALERT_RE.search(source or "")
    return match.group(1).lower() if match else "unknown"


def extract_features(text: str) -> list[str]:
    src = (text or "").lower()
    features = [name for name, pattern in FEATURE_PATTERNS if re.search(pattern, src, re.IGNORECASE)]
    return sorted(dict.fromkeys(features))


def infer_criterion_code(comment_text: str, anchor_features: Iterable[str]) -> str:
    features = set(anchor_features)
    text = (comment_text or "").lower()
    if {"columns", "lower", "replace"} & features or "snake" in text or "назван" in text:
        return "games_columns_snake_case"
    if {"to_numeric", "user_score", "eu_sales", "jp_sales"} & features or (
        "тип" in text and any(token in text for token in ["user_score", "eu_sales", "jp_sales", "tbd"])
    ):
        return "games_scores_numeric_conversion"
    if {"isna_sum", "isna_mean"} & features or "количество пропуск" in text or "доля пропуск" in text:
        return "games_missing_values_quantified"
    if {"fillna", "dropna", "rating"} & features or "non_rating" in text or "пропуск" in text:
        return "games_missing_values_decision"
    if {"duplicated", "drop_duplicates"} & features or "дубликат" in text:
        return "games_duplicates_checked"
    if {"genre", "lower"} <= features or "неявн" in text:
        return "games_genre_normalized"
    if "year" in features or "2000" in text or "2013" in text:
        return "games_actual_period_filter"
    if "score_category" in features or "категор" in text:
        return "games_score_categories"
    if {"platform", "head7"} & features or "топ-7" in text or "top-7" in text:
        return "games_top7_platforms"
    if "read_csv" in features:
        return "games_dataset_loaded"
    if {"head", "info"} & features:
        return "games_initial_overview"
    return ""


def _cell_source(cell: Any) -> str:
    return normalize_cell_source(cell.get("source", ""))


def _raw_cell_source(cell: Any) -> str:
    source = cell.get("source", "")
    if isinstance(source, list):
        return "".join(source)
    if not isinstance(source, str):
        return str(source or "")
    return source


def _cell_signature(cell: Any) -> str:
    source = _cell_source(cell)
    return f"{cell.get('cell_type', '')}:{content_hash(source)}"


def _section_path_before(cells: list[Any], idx: int) -> list[str]:
    path: list[tuple[int, str]] = []
    for cell in cells[:idx]:
        if cell.get("cell_type") != "markdown":
            continue
        src = _raw_cell_source(cell)
        role = infer_notebook_comment_role(src)
        if is_review_role_cell(role) or role == "student":
            continue
        for raw_line in src.splitlines():
            line = _WS_RE.sub(" ", raw_line).strip()
            match = _HEADING_RE.match(line)
            if not match:
                continue
            level = len(match.group(1))
            title = _TAG_RE.sub("", match.group(2)).strip(" #*-")
            path = [(lvl, val) for lvl, val in path if lvl < level]
            path.append((level, title))
    return [title for _, title in path[-3:]]


def _nearest_student_work_cell(cells: list[Any], idx: int) -> tuple[int | None, Any | None]:
    for pos in range(idx, -1, -1):
        cell = cells[pos]
        source = _cell_source(cell)
        role = infer_notebook_comment_role(source)
        if is_review_role_cell(role) or role == "student":
            continue
        if cell.get("cell_type") in {"code", "markdown"} and source.strip():
            return pos, cell
    return None, None


def _next_student_work_text(cells: list[Any], idx: int) -> str:
    for pos in range(idx + 1, len(cells)):
        cell = cells[pos]
        source = _cell_source(cell)
        role = infer_notebook_comment_role(source)
        if is_review_role_cell(role) or role == "student":
            continue
        if source.strip():
            return source[:2000]
    return ""


def _review_iteration(source: str) -> int:
    match = re.search(r"Комментарий ревьюера\s*(\d+)", source, re.IGNORECASE)
    return int(match.group(1)) if match else 1


def extract_reviewer_insertions(
    source_notebook: Path | str,
    reviewed_notebook: Path | str,
    *,
    project_type: str,
) -> list[dict[str, Any]]:
    source_path = Path(source_notebook)
    reviewed_path = Path(reviewed_notebook)
    source_nb = nbformat.read(source_path, as_version=4)
    reviewed_nb = nbformat.read(reviewed_path, as_version=4)
    source_cells = list(source_nb.cells)
    reviewed_cells = list(reviewed_nb.cells)
    source_sigs = [_cell_signature(cell) for cell in source_cells]

    rows: list[dict[str, Any]] = []
    source_cursor = 0
    last_source_idx: int | None = None

    for reviewed_idx, cell in enumerate(reviewed_cells):
        sig = _cell_signature(cell)
        if source_cursor < len(source_sigs) and sig == source_sigs[source_cursor]:
            last_source_idx = source_cursor
            source_cursor += 1
            continue

        source = _cell_source(cell)
        role = infer_notebook_comment_role(source)
        remaining_match = None
        for pos in range(source_cursor, len(source_sigs)):
            if source_sigs[pos] == sig:
                remaining_match = pos
                break

        if is_review_role_cell(role) and remaining_match is None:
            anchor_idx, anchor_cell = _nearest_student_work_cell(source_cells, last_source_idx or 0)
            anchor_source = _cell_source(anchor_cell) if anchor_cell is not None else ""
            anchor_features = extract_features(anchor_source)
            comment_text = plain_text(source)
            row = {
                "example_id": f"{project_type}_{reviewed_path.stem}_{reviewed_idx}",
                "project_type": project_type,
                "source_notebook": source_path.name,
                "reviewed_notebook": reviewed_path.name,
                "review_iteration": _review_iteration(source),
                "alert_color": detect_alert_color(source),
                "comment_text": comment_text,
                "criterion_code": infer_criterion_code(comment_text, anchor_features),
                "section_path": _section_path_before(reviewed_cells, reviewed_idx),
                "insert_position": "after_student_cell",
                "anchor_before": {
                    "cell_type": anchor_cell.get("cell_type", "") if anchor_cell is not None else "",
                    "features": anchor_features,
                    "content_hash": content_hash(anchor_source) if anchor_source else "",
                },
                "local_context": {
                    "before_text": anchor_source[:2000],
                    "after_text": _next_student_work_text(source_cells, last_source_idx or 0),
                },
            }
            rows.append(row)
            continue

        if remaining_match is not None:
            last_source_idx = remaining_match
            source_cursor = remaining_match + 1

    return rows


def load_insertion_rows(path: Path | str | None) -> list[dict[str, Any]]:
    if not path:
        return []
    base = Path(path)
    paths = sorted(base.glob("*.jsonl")) if base.is_dir() else [base]
    rows: list[dict[str, Any]] = []
    for item in paths:
        if not item.exists():
            continue
        for line in item.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def write_insertion_rows(rows: list[dict[str, Any]], path: Path | str, *, append: bool = True) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict[str, Any]] = load_insertion_rows(out) if append and out.exists() else []
    by_id = {str(row.get("example_id") or ""): row for row in existing if row.get("example_id")}
    for row in rows:
        eid = str(row.get("example_id") or "")
        if eid:
            by_id[eid] = row
    payload = list(by_id.values()) if by_id else rows
    out.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in payload) + ("\n" if payload else ""),
        encoding="utf-8",
    )


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "") if len(t) > 2}


def _jaccard(a: str, b: str) -> float:
    left = _tokens(a)
    right = _tokens(b)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _artifact_features(artifact: dict[str, Any]) -> list[str]:
    return extract_features(str(artifact.get("normalized_text") or artifact.get("raw_text") or ""))


def choose_insertion_anchor(
    artifacts: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    *,
    project_type: str | None,
    criterion_code: str,
    alert_color: str,
    query_text: str,
    min_score: float = 0.45,
) -> InsertionAnchor | None:
    filtered_rows = []
    for row in rows:
        row_project = str(row.get("project_type") or row.get("source_project") or "")
        if project_type and row_project and row_project != project_type:
            continue
        row_color = str(row.get("alert_color") or "")
        if row_color == "success":
            continue
        if row_color and row_color != "unknown" and row_color != alert_color:
            continue
        row_criterion = str(row.get("criterion_code") or "")
        if row_criterion and row_criterion != criterion_code:
            continue
        filtered_rows.append(row)

    if not filtered_rows:
        return None

    best: InsertionAnchor | None = None
    for artifact in artifacts:
        meta = artifact.get("metadata_json") or artifact.get("metadata") or {}
        if meta.get("is_reviewer_comment") or meta.get("is_middle_reviewer_comment") or meta.get("is_student_comment"):
            continue
        pos = artifact.get("position_idx")
        if pos is None:
            continue
        art_features = set(_artifact_features(artifact))
        art_text = str(artifact.get("normalized_text") or "")
        section = str(artifact.get("section_name") or "")
        for row in filtered_rows:
            row_features = set((row.get("anchor_before") or {}).get("features") or [])
            feature_score = len(art_features & row_features) / len(row_features) if row_features else 0.0
            text_score = max(
                _jaccard(query_text, str(row.get("comment_text") or "")),
                _jaccard(art_text, str((row.get("local_context") or {}).get("before_text") or "")),
            )
            criterion_score = 1.0 if str(row.get("criterion_code") or "") == criterion_code else 0.0
            color_score = 1.0 if str(row.get("alert_color") or "") == alert_color else 0.0
            section_path = " ".join(str(x) for x in (row.get("section_path") or []))
            section_score = 1.0 if section and section.lower() in section_path.lower() else 0.0
            score = (
                0.45 * feature_score
                + 0.25 * text_score
                + 0.15 * criterion_score
                + 0.10 * color_score
                + 0.05 * section_score
            )
            if best is None or score > best.score:
                best = InsertionAnchor(position_idx=int(pos), score=round(score, 4), example=row)

    if best is None or best.score < min_score:
        return None
    return best
