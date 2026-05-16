from __future__ import annotations

import json
from pathlib import Path

from scripts.import_project_brief import (
    build_draft_criteria,
    extract_datasets,
    extract_year_bounds,
    import_project_brief,
    slugify,
)


def test_slugify_transliterates_russian_title() -> None:
    assert slugify("Спринт 7. Предобработка данных") == "sprint_7_predobrabotka_dannyh"
    assert slugify("Games preprocessing!") == "games_preprocessing"


def test_extract_project_brief_signals() -> None:
    text = """
    Данные /datasets/new_games.csv содержат продажи игр.
    Отберите данные за период с 2000 по 2013 год включительно.
    """
    assert extract_datasets(text) == ["/datasets/new_games.csv"]
    assert extract_year_bounds(text) == (2000, 2013)


def test_build_draft_criteria_from_practicum_like_text() -> None:
    text = """
    Нужно загрузить /datasets/new_games.csv через pandas.
    Познакомьтесь с данными: выведите первые строки и результат метода info().
    Приведите все столбцы к snake_case.
    Посчитайте пропуски и проверьте дубликаты.
    Отберите данные за период с 2000 по 2013 год включительно.
    Категоризируйте оценки и выделите топ-7 платформ.
    Сделайте вывод.
    """
    criteria, meta = build_draft_criteria("games_preprocessing", text, kind="ipynb")
    codes = {c["code"] for c in criteria}
    assert "games_preprocessing_intro" in codes
    assert "games_preprocessing_dataset_loaded" in codes
    assert "games_preprocessing_period_filter" in codes
    assert "games_preprocessing_top_7" in codes
    assert meta["datasets"] == ["/datasets/new_games.csv"]
    assert meta["year_bounds"] == [2000, 2013]


def test_import_project_brief_writes_kb_metadata_and_criteria(tmp_path: Path) -> None:
    source = tmp_path / "brief.md"
    source.write_text(
        """# Project Games

Нужно загрузить /datasets/new_games.csv.
Познакомьтесь с данными: выведите первые строки и результат метода info().
Посчитайте пропуски и проверьте дубликаты.
Отберите данные за период с 2000 по 2013 год включительно.
Категоризируйте оценки и выделите топ-7 платформ.
Сделайте вывод.
""",
        encoding="utf-8",
    )
    out = import_project_brief(
        source,
        slug="games_preprocessing",
        kind="ipynb",
        title=None,
        course_kb_dir=tmp_path / "kb",
        criteria_dir=tmp_path / "criteria",
        overwrite=False,
    )

    assert out["criteria_map_code"] == "ipynb_games_preprocessing_v1"
    kb_path = Path(out["course_kb_path"])
    meta_path = Path(out["metadata_path"])
    criteria_path = Path(out["criteria_map_path"])
    assert kb_path.read_text(encoding="utf-8").startswith("# Project Games")

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["slug"] == "games_preprocessing"
    assert meta["criteria_map_code"] == "ipynb_games_preprocessing_v1"
    assert meta["extraction"]["datasets"] == ["/datasets/new_games.csv"]

    criteria = json.loads(criteria_path.read_text(encoding="utf-8"))["criteria"]
    assert criteria
    assert all("category" in item for item in criteria)

    try:
        import_project_brief(
            source,
            slug="games_preprocessing",
            kind="ipynb",
            title=None,
            course_kb_dir=tmp_path / "kb",
            criteria_dir=tmp_path / "criteria",
            overwrite=False,
        )
    except FileExistsError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected existing outputs to require --overwrite")
