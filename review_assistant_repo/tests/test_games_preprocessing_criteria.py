from __future__ import annotations

import json
from pathlib import Path


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
    assert len(rows) == 14
    assert {row["status"] for row in rows} == {"pass"}

    codes = {row["criterion_code"] for row in rows}
    assert "games_dataset_loaded" in codes
    assert "games_actual_period_filter" in codes
    assert "games_top7_platforms" in codes
