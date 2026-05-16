from __future__ import annotations

from pathlib import Path

import nbformat
from nbformat.v4 import new_markdown_cell, new_notebook

from app.retrieval.senior_review import (
    extract_senior_review_notebook,
    parse_guidance_cell,
    rubric_to_markdown,
)
from scripts.import_senior_review_notebook import import_senior_review_notebook


def test_parse_color_coded_criteria_cell() -> None:
    src = """> <font color='#31708f'>🕵️♂️ **Критерии проверки:**
> - <font color='#3c763d'>👍 Всё хорошо.
> - <font color='#8a6d3b'>📝 Можно улучшить.
> - <font color='#a94442'>✍ Нужно исправить.
"""
    block = parse_guidance_cell(src, cell_idx=3, section_name="### 2.1. Названия столбцов")
    assert block is not None
    assert block.block_type == "criteria"
    assert block.criterion_codes == ["games_columns_snake_case"]
    assert [item.alert_color for item in block.items] == ["success", "warning", "danger"]
    assert block.items[2].level == "required_fix"


def test_extract_senior_review_notebook_to_runtime_rows(tmp_path: Path) -> None:
    nb = new_notebook(
        cells=[
            new_markdown_cell("# Авторское решение"),
            new_markdown_cell("### 2.1. Названия (метки) столбцов датафрейма:"),
            new_markdown_cell(
                """> <font color='#31708f'>🕵️♂️ **Критерии проверки:**
> - <font color='#3c763d'>👍 Все столбцы были приведены к нотации `snake_case` с помощью метода `.rename()`.
> - <font color='#a94442'>✍ Названия столбцов остались без изменения.
"""
            ),
            new_markdown_cell(
                """> <font color='#31708f'>🧙‍♂ **Комментарий автора:** Можно использовать `.rename()` или замену `columns`.
"""
            ),
        ]
    )
    path = tmp_path / "senior.ipynb"
    nbformat.write(nb, path)

    payload = extract_senior_review_notebook(path, source_project="games_preprocessing")
    assert payload["meta"]["guidance_blocks_count"] == 2
    assert payload["meta"]["runtime_rows_count"] >= 3
    rows = payload["runtime_rows"]
    assert any(row["criterion_code"] == "games_columns_snake_case" for row in rows)
    assert any("alert_danger" in row["tags"] for row in rows)
    md = rubric_to_markdown(payload)
    assert "Color policy" in md
    assert "games_columns_snake_case" in md


def test_import_senior_review_notebook_outputs_files(tmp_path: Path) -> None:
    nb = new_notebook(
        cells=[
            new_markdown_cell("### 3. Фильтрация данных по условию проекта"),
            new_markdown_cell(
                """> <font color='#31708f'>🕵️♂️ **Критерии проверки:**
> - <font color='#3c763d'>👍 Фильтрация данных проведена корректно (с 2000 по 2013 годы включительно).
> - <font color='#a94442'>✍ Фильтрация данных не была проведена корректно.
"""
            ),
        ]
    )
    path = tmp_path / "senior.ipynb"
    nbformat.write(nb, path)

    result = import_senior_review_notebook(
        path,
        project="games_preprocessing",
        output_json=tmp_path / "guidance.json",
        output_md=tmp_path / "guidance.md",
        runtime_out=tmp_path / "runtime.jsonl",
        overwrite=False,
    )
    assert result["runtime_rows"] == 2
    assert (tmp_path / "guidance.json").is_file()
    assert (tmp_path / "guidance.md").read_text(encoding="utf-8").startswith("# Senior review guidance")
    runtime = (tmp_path / "runtime.jsonl").read_text(encoding="utf-8")
    assert "games_actual_period_filter" in runtime

    try:
        import_senior_review_notebook(
            path,
            project="games_preprocessing",
            output_json=tmp_path / "guidance.json",
            output_md=tmp_path / "guidance.md",
            runtime_out=tmp_path / "runtime.jsonl",
            overwrite=False,
        )
    except FileExistsError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected existing files to require --overwrite")
