from __future__ import annotations

import json
from pathlib import Path

import nbformat
from fastapi.testclient import TestClient


def _write_games_project_notebook(path: Path) -> None:
    notebook = {
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "## Введение\n\n"
                    "Цель проекта — изучить исторические данные о продажах игр, "
                    "оценках пользователей и критиков, подготовить данные за 2000-2013 годы "
                    "и выделить платформы для дальнейшего анализа."
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "import pandas as pd\n"
                    "df = pd.read_csv('/datasets/new_games.csv')\n"
                    "display(df.head())\n"
                    "df.info()"
                ],
            },
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "После первичного обзора видно, какой объём данных доступен, "
                    "в каких столбцах есть пропуски, какие типы требуют преобразования "
                    "и какие названия столбцов нужно привести к удобному виду."
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "df.columns = df.columns.str.lower().str.replace(' ', '_')\n"
                    "df['eu_sales'] = pd.to_numeric(df['eu_sales'], errors='coerce')\n"
                    "df['jp_sales'] = pd.to_numeric(df['jp_sales'], errors='coerce')\n"
                    "df['user_score'] = pd.to_numeric(df['user_score'], errors='coerce')\n"
                    "df['critic_score'] = pd.to_numeric(df['critic_score'], errors='coerce')"
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "missing_abs = df.isna().sum()\n"
                    "missing_rel = df.isna().mean() * 100\n"
                    "display(pd.concat([missing_abs, missing_rel], axis=1))"
                ],
            },
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "Пропуски в оценках оставляем как неизвестные значения, "
                    "часть строк с критически важными пропусками можно удалить, "
                    "а для категориальных полей использовать значение-индикатор."
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "df['rating'] = df['rating'].fillna('unknown')\n"
                    "df = df.dropna(subset=['name', 'genre'])"
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "for col in ['genre', 'platform']:\n"
                    "    print(col, df[col].str.lower().unique()[:10])\n"
                    "df['rating'] = df['rating'].str.upper()\n"
                    "duplicates_count = df.duplicated().sum()\n"
                    "df = df.drop_duplicates()"
                ],
            },
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "После предобработки удалено 12 строк, это меньше 1% исходного объёма. "
                    "Такое удаление не должно исказить дальнейший анализ."
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "df_actual = df[(df['year_of_release'] >= 2000) & (df['year_of_release'] <= 2013)]"
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "def score_category(value):\n"
                    "    if value >= 8:\n"
                    "        return 'высокая оценка'\n"
                    "    if value >= 3:\n"
                    "        return 'средняя оценка'\n"
                    "    return 'низкая оценка'\n"
                    "df_actual['user_score_category'] = df_actual['user_score'].apply(score_category)\n"
                    "df_actual['critic_score_category'] = df_actual['critic_score'].apply(score_category)"
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "top_platforms = df_actual['platform'].value_counts().head(7)\n"
                    "display(top_platforms)"
                ],
            },
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "## Вывод\n\n"
                    "Данные подготовлены для анализа: выбран период 2000-2013, "
                    "оценки категоризированы, а топ платформ определён по количеству игр."
                ],
            },
        ],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    for idx, cell in enumerate(notebook["cells"]):
        cell["id"] = f"games-{idx:02d}"
    path.write_text(json.dumps(notebook, ensure_ascii=False), encoding="utf-8")


def test_games_preprocessing_criteria_map_passes_representative_notebook(client, tmp_path):
    notebook_path = tmp_path / "games_preprocessing.ipynb"
    _write_games_project_notebook(notebook_path)

    with notebook_path.open("rb") as f:
        upload = client.post(
            "/api/v1/projects/upload",
            data={"criteria_map_code": "notebook_games_preprocessing_v1"},
            files={"file": (notebook_path.name, f, "application/x-ipynb+json")},
        )
    assert upload.status_code == 200, upload.text
    project_id = upload.json()["project_id"]

    review = client.post(f"/api/v1/projects/{project_id}/review")
    assert review.status_code == 200, review.text
    assert review.json()["final_verdict"] == "pass"

    findings = client.get(f"/api/v1/projects/{project_id}/findings")
    assert findings.status_code == 200
    rows = findings.json()
    assert len(rows) == 15
    assert {row["status"] for row in rows} == {"pass"}

    codes = {row["criterion_code"] for row in rows}
    assert "games_dataset_loaded" in codes
    assert "games_actual_period_filter" in codes
    assert "games_top7_platforms" in codes


def test_games_preprocessing_accepts_split_overview_and_groupby_top7(client, tmp_path):
    notebook_path = tmp_path / "games_split_cells.ipynb"
    _write_games_project_notebook(notebook_path)
    data = json.loads(notebook_path.read_text(encoding="utf-8"))
    data["cells"][1]["source"] = ["import pandas as pd\n", "df = pd.read_csv('/datasets/new_games.csv')"]
    data["cells"].insert(
        2,
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "id": "games-extra-head",
            "source": ["df.head()"],
        },
    )
    data["cells"].insert(
        3,
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "id": "games-extra-info",
            "source": ["df.info()"],
        },
    )
    data["cells"][13]["source"] = [
        "top_platforms = (\n",
        "    df_actual.groupby('platform')['name']\n",
        "    .count()\n",
        "    .sort_values(ascending=False)\n",
        "    .head(7)\n",
        ")\n",
        "display(top_platforms)",
    ]
    notebook_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    with notebook_path.open("rb") as f:
        upload = client.post(
            "/api/v1/projects/upload",
            data={"criteria_map_code": "notebook_games_preprocessing_v1"},
            files={"file": (notebook_path.name, f, "application/x-ipynb+json")},
        )
    assert upload.status_code == 200, upload.text
    project_id = upload.json()["project_id"]

    review = client.post(f"/api/v1/projects/{project_id}/review")
    assert review.status_code == 200, review.text

    rows = client.get(f"/api/v1/projects/{project_id}/findings").json()
    by_code = {row["criterion_code"]: row["status"] for row in rows}
    assert by_code["games_initial_overview"] == "pass"
    assert by_code["games_top7_platforms"] == "pass"


def test_games_preprocessing_accepts_reviewer_pair_patterns(client, tmp_path):
    notebook_path = tmp_path / "games_pair_patterns.ipynb"
    _write_games_project_notebook(notebook_path)
    data = json.loads(notebook_path.read_text(encoding="utf-8"))
    data["cells"][3]["source"] = [
        "df.columns = [x.lower().replace(' ', '_') for x in df.columns.values]\n",
        "df['eu_sales'] = pd.to_numeric(df['eu_sales'], errors='coerce')\n",
        "df['jp_sales'] = pd.to_numeric(df['jp_sales'], errors='coerce')\n",
        "df['user_score'] = pd.to_numeric(df['user_score'], errors='coerce')\n",
        "df['critic_score'] = pd.to_numeric(df['critic_score'], errors='coerce')",
    ]
    data["cells"][4]["source"] = ["pd.DataFrame(df.isna().sum()).style.background_gradient('coolwarm')"]
    data["cells"].insert(
        5,
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "id": "games-missing-relative",
            "source": ["pd.DataFrame(round(df.isna().mean() * 100, 2)).style.background_gradient('coolwarm')"],
        },
    )
    notebook_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    with notebook_path.open("rb") as f:
        upload = client.post(
            "/api/v1/projects/upload",
            data={"criteria_map_code": "notebook_games_preprocessing_v1"},
            files={"file": (notebook_path.name, f, "application/x-ipynb+json")},
        )
    assert upload.status_code == 200, upload.text
    project_id = upload.json()["project_id"]

    review = client.post(f"/api/v1/projects/{project_id}/review")
    assert review.status_code == 200, review.text

    rows = client.get(f"/api/v1/projects/{project_id}/findings").json()
    by_code = {row["criterion_code"]: row["status"] for row in rows}
    assert by_code["games_columns_snake_case"] == "pass"
    assert by_code["games_missing_values_quantified"] == "pass"


def test_reviewer_insertion_memory_places_failed_comment_near_matching_cell(tmp_path, monkeypatch):
    notebook_path = tmp_path / "games_memory_anchor.ipynb"
    _write_games_project_notebook(notebook_path)
    data = json.loads(notebook_path.read_text(encoding="utf-8"))
    data["cells"][11]["source"] = [
        "grouped_data = df_actual.groupby('platform')['name'].count()\n",
        "display(grouped_data.sort_values(ascending=False))",
    ]
    notebook_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    memory_path = tmp_path / "reviewer_insertions.jsonl"
    memory_row = {
        "example_id": "top7_example",
        "project_type": "games_preprocessing",
        "alert_color": "danger",
        "criterion_code": "games_top7_platforms",
        "comment_text": "Выведи топ-7 платформ по количеству игр.",
        "anchor_before": {"cell_type": "code", "features": ["groupby", "platform"]},
        "local_context": {
            "before_text": "grouped_data = df_actual.groupby('platform')['name'].count()",
        },
    }
    memory_path.write_text(json.dumps(memory_row, ensure_ascii=False) + "\n", encoding="utf-8")

    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("FILES_ROOT", str(data_dir / "files"))
    monkeypatch.setenv("EXPORTS_ROOT", str(data_dir / "exports"))
    monkeypatch.setenv("ENABLE_NOTEBOOK_EXECUTION", "false")
    monkeypatch.setenv("ENABLE_REVIEWER_INSERTION_MEMORY", "true")
    monkeypatch.setenv("REVIEWER_INSERTIONS_PATH", str(memory_path))
    monkeypatch.setenv("REVIEWER_INSERTION_MIN_SCORE", "0.45")

    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    with TestClient(create_app()) as client:
        with notebook_path.open("rb") as f:
            upload = client.post(
                "/api/v1/projects/upload",
                data={
                    "criteria_map_code": "notebook_games_preprocessing_v1",
                    "review_training_project": "games_preprocessing",
                },
                files={"file": (notebook_path.name, f, "application/x-ipynb+json")},
            )
        assert upload.status_code == 200, upload.text
        project_id = upload.json()["project_id"]

        review = client.post(f"/api/v1/projects/{project_id}/review")
        assert review.status_code == 200, review.text
        assert review.json()["final_verdict"] == "revise"

        reviewed_resp = client.get(f"/api/v1/projects/{project_id}/export/reviewed_notebook")
        assert reviewed_resp.status_code == 200

    reviewed = nbformat.reads(reviewed_resp.content.decode("utf-8"), as_version=4)
    sources = [cell.source for cell in reviewed.cells]
    target_idx = next(i for i, source in enumerate(sources) if "grouped_data = df_actual.groupby('platform')" in source)
    assert "Топ-7 платформ" in sources[target_idx + 1] or "топ-7 платформ" in sources[target_idx + 1]
