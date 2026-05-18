from __future__ import annotations

from pathlib import Path

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

from app.retrieval.reviewer_insertions import (
    choose_insertion_anchor,
    detect_alert_color,
    extract_reviewer_insertions,
    infer_praise_code,
    load_insertion_rows,
    write_insertion_rows,
)


def _write_nb(path: Path, cells: list) -> None:
    nbformat.write(new_notebook(cells=cells), path)


def test_extract_reviewer_insertions_finds_new_review_comment(tmp_path: Path):
    source = tmp_path / "source.ipynb"
    reviewed = tmp_path / "reviewed.ipynb"
    _write_nb(
        source,
        [
            new_markdown_cell("## 2.3. Наличие пропусков"),
            new_code_cell("df['rating'] = df['rating'].fillna('non rating')"),
            new_markdown_cell('<div class="alert alert-info"><h2>Комментарий студента:</h2>fixed</div>'),
        ],
    )
    _write_nb(
        reviewed,
        [
            new_markdown_cell("## 2.3. Наличие пропусков"),
            new_code_cell("df['rating'] = df['rating'].fillna('non rating')"),
            new_markdown_cell(
                '<div class="alert alert-block alert-danger">'
                "<h2>Комментарий ревьюера</h2><b>На доработку:</b> замени rating на non_rating"
                "</div>"
            ),
            new_markdown_cell('<div class="alert alert-info"><h2>Комментарий студента:</h2>fixed</div>'),
        ],
    )

    rows = extract_reviewer_insertions(source, reviewed, project_type="games_preprocessing")

    assert len(rows) == 1
    row = rows[0]
    assert row["alert_color"] == "danger"
    assert row["insert_position"] == "after_student_cell"
    assert row["criterion_code"] == "games_missing_values_decision"
    assert row["anchor_before"]["cell_type"] == "code"
    assert {"fillna", "rating"}.issubset(set(row["anchor_before"]["features"]))
    assert "Комментарий студента" not in row["comment_text"]


def test_extract_reviewer_insertions_ignores_existing_source_comments(tmp_path: Path):
    source = tmp_path / "source.ipynb"
    reviewed = tmp_path / "reviewed.ipynb"
    old_review = '<div class="alert alert-success"><h2>Комментарий ревьюера</h2>ok</div>'
    new_review = '<div class="alert alert-warning"><h2>Комментарий ревьюера 2</h2>try apply</div>'
    _write_nb(source, [new_code_cell("df.columns"), new_markdown_cell(old_review)])
    _write_nb(reviewed, [new_code_cell("df.columns"), new_markdown_cell(old_review), new_markdown_cell(new_review)])

    rows = extract_reviewer_insertions(source, reviewed, project_type="games_preprocessing")

    assert len(rows) == 1
    assert rows[0]["alert_color"] == "warning"
    assert rows[0]["review_iteration"] == 2


def test_extract_reviewer_insertions_skips_opening_comment(tmp_path: Path):
    source = tmp_path / "source.ipynb"
    reviewed = tmp_path / "reviewed.ipynb"
    opening = (
        '<div class="alert alert-success"><h2>Комментарий ревьюера ✔️</h2>'
        "Привет! Меня зовут Анна, я буду твоим ревьюером. "
        "Предлагаю общаться на ты. Пожалуйста, не удаляй комментарии ревьюера."
        "</div>"
    )
    review = (
        '<div class="alert alert-danger"><h2>Комментарий ревьюера ❌</h2>'
        "Замени пропуски в rating на non_rating."
        "</div>"
    )
    _write_nb(source, [new_markdown_cell("## Пропуски"), new_code_cell("df['rating'].fillna('unknown')")])
    _write_nb(reviewed, [new_markdown_cell(opening), new_markdown_cell("## Пропуски"), new_code_cell("df['rating'].fillna('unknown')"), new_markdown_cell(review)])

    rows = extract_reviewer_insertions(source, reviewed, project_type="games_preprocessing")

    assert len(rows) == 1
    assert rows[0]["alert_color"] == "danger"
    assert "Меня зовут" not in rows[0]["comment_text"]


def test_extract_reviewer_insertions_skips_final_comment(tmp_path: Path):
    source = tmp_path / "source.ipynb"
    reviewed = tmp_path / "reviewed.ipynb"
    regular_review = (
        '<div class="alert alert-warning"><h2>Комментарий ревьюера ⚠️</h2>'
        "Добавь проверку результата фильтрации через min и max."
        "</div>"
    )
    final_review = (
        '<div class="alert alert-info"><h2>Итоговый комментарий ревьюера ✔️</h2>'
        "Проект принят. Мне понравилась структура работы, замечания перечислены выше."
        "</div>"
    )
    _write_nb(source, [new_markdown_cell("## Фильтрация"), new_code_cell("df_actual = df[df['year'] >= 2000]")])
    _write_nb(
        reviewed,
        [
            new_markdown_cell("## Фильтрация"),
            new_code_cell("df_actual = df[df['year'] >= 2000]"),
            new_markdown_cell(regular_review),
            new_markdown_cell(final_review),
        ],
    )

    rows = extract_reviewer_insertions(source, reviewed, project_type="games_preprocessing")

    assert len(rows) == 1
    assert rows[0]["alert_color"] == "warning"
    assert "Итоговый комментарий" not in rows[0]["comment_text"]


def test_extract_reviewer_insertions_marks_non_criterion_praise(tmp_path: Path):
    source = tmp_path / "source.ipynb"
    reviewed = tmp_path / "reviewed.ipynb"
    praise = (
        '<div class="alert alert-success"><h2>Комментарий ревьюера ✔️</h2>'
        "Молодец, что импортируешь библиотеку pandas отдельно в первой ячейке. "
        "Это правило хорошего тона для будущих коллег."
        "</div>"
    )
    _write_nb(source, [new_markdown_cell("## 1. Загрузка данных"), new_code_cell("import pandas as pd")])
    _write_nb(reviewed, [new_markdown_cell("## 1. Загрузка данных"), new_code_cell("import pandas as pd"), new_markdown_cell(praise)])

    rows = extract_reviewer_insertions(source, reviewed, project_type="games_preprocessing")

    assert len(rows) == 1
    assert rows[0]["criterion_code"] == ""
    assert rows[0]["comment_kind"] == "non_criterion_praise"
    assert rows[0]["praise_code"] == "praise_imports_separated"


def test_detect_alert_color_supports_custom_review_emoji():
    assert detect_alert_color("#### ✅ Python Enhancement Proposal №8") == "success"
    assert detect_alert_color("#### ⚠️ Структура и оформление проекта") == "warning"
    assert detect_alert_color("#### ⛔ Обязателен к исправлению") == "danger"
    assert detect_alert_color("#### 🚩 Красный флаг") == "danger"


def test_infer_praise_code_uses_section_and_text():
    assert (
        infer_praise_code(
            "Отлично по описанию. Цели и задачи ясны.",
            ["Содержимое проекта"],
            [],
        )
        == "praise_project_intro_context"
    )
    assert (
        infer_praise_code(
            "Ты правильно делаешь, что проверяешь количество удаленных данных.",
            ["2.4. Явные и неявные дубликаты"],
            [],
        )
        == "praise_removed_rows_control"
    )


def test_write_and_load_insertion_rows_dedupes_by_example_id(tmp_path: Path):
    path = tmp_path / "memory.jsonl"
    row = {"example_id": "same", "project_type": "games_preprocessing"}

    write_insertion_rows([row], path)
    write_insertion_rows([{**row, "alert_color": "danger"}], path)

    rows = load_insertion_rows(path)
    assert rows == [{"example_id": "same", "project_type": "games_preprocessing", "alert_color": "danger"}]


def test_choose_insertion_anchor_uses_feature_and_criterion_match():
    rows = [
        {
            "example_id": "rating",
            "project_type": "games_preprocessing",
            "alert_color": "danger",
            "criterion_code": "games_missing_values_decision",
            "comment_text": "замени пропуски в rating на non_rating",
            "anchor_before": {"features": ["fillna", "rating"]},
            "local_context": {"before_text": "df['rating'] = df['rating'].fillna('non_rating')"},
        }
    ]
    artifacts = [
        {
            "artifact_type": "code_cell",
            "position_idx": 1,
            "normalized_text": "df.columns = [x.lower() for x in df.columns]",
            "metadata_json": {},
        },
        {
            "artifact_type": "code_cell",
            "position_idx": 2,
            "normalized_text": "df['rating'] = df['rating'].fillna('non_rating')",
            "metadata_json": {},
        },
    ]

    anchor = choose_insertion_anchor(
        artifacts,
        rows,
        project_type="games_preprocessing",
        criterion_code="games_missing_values_decision",
        alert_color="danger",
        query_text="обработай пропуски в rating",
        min_score=0.45,
    )

    assert anchor is not None
    assert anchor.position_idx == 2
    assert anchor.example["example_id"] == "rating"


def test_choose_insertion_anchor_returns_none_for_low_score():
    rows = [
        {
            "example_id": "columns",
            "project_type": "games_preprocessing",
            "alert_color": "danger",
            "criterion_code": "games_columns_snake_case",
            "comment_text": "приведи названия столбцов",
            "anchor_before": {"features": ["columns", "lower", "replace"]},
        }
    ]
    artifacts = [{"artifact_type": "code_cell", "position_idx": 1, "normalized_text": "x = 1", "metadata_json": {}}]

    assert (
        choose_insertion_anchor(
            artifacts,
            rows,
            project_type="games_preprocessing",
            criterion_code="games_top7_platforms",
            alert_color="danger",
            query_text="выведи топ-7 платформ",
            min_score=0.45,
        )
        is None
    )
