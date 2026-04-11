from __future__ import annotations

import re

from app.parsers.base import ParsedArtifact

_INTRO_PAT = re.compile(
    r"введен|цель|задач|описание данных|постановк|business\s*context",
    re.IGNORECASE,
)
_LOAD_PAT = re.compile(
    r"read_csv|read_excel|read_sql|pd\.read|load_dataset|fetch|download|from\s+postgres|sqlalchemy",
    re.IGNORECASE,
)
_CHECK_PAT = re.compile(
    r"\.head\(|\.info\(|\.describe\(|\.isna\(|\.isnull\(|duplicated\(|shape|dtypes",
    re.IGNORECASE,
)
_PRE_PAT = re.compile(
    r"fillna|dropna|replace|astype|encoder|standardscaler|normalize|pipeline|train_test_split",
    re.IGNORECASE,
)
_EDA_PAT = re.compile(
    r"plot|hist|boxplot|scatter|seaborn|sns\.|matplotlib|plt\.|value_counts|corr\(|groupby\(|eda|исследов",
    re.IGNORECASE,
)
_MODEL_PAT = re.compile(
    r"fit\(|LogisticRegression|RandomForest|XGB|CatBoost|LinearRegression|model\.|cross_val|GridSearch|hyperparam",
    re.IGNORECASE,
)
_EVAL_PAT = re.compile(
    r"accuracy|precision|recall|f1|roc_auc|rmse|mae|r2_score|confusion_matrix|classification_report|метрик",
    re.IGNORECASE,
)
_CONC_PAT = re.compile(
    r"вывод|итог|заключен|рекомендац|summary|conclusion",
    re.IGNORECASE,
)


def infer_flow_section(source: str, cell_type: str) -> str | None:
    """Return a coarse section label from raw cell source (best-effort)."""
    text = source or ""
    text.lower()
    if cell_type == "markdown":
        if _INTRO_PAT.search(text):
            return "intro"
        if _CONC_PAT.search(text):
            return "conclusions"
        if _EDA_PAT.search(text):
            return "eda"
    if _CONC_PAT.search(text) and cell_type == "markdown":
        return "conclusions"
    if _MODEL_PAT.search(text):
        return "modeling"
    if _EVAL_PAT.search(text):
        return "evaluation"
    if _EDA_PAT.search(text):
        return "eda"
    if _PRE_PAT.search(text):
        return "preprocessing"
    if _CHECK_PAT.search(text):
        return "data_check"
    if _LOAD_PAT.search(text):
        return "data_loading"
    return None


def assign_sections_linear(artifacts: list[ParsedArtifact]) -> None:
    """
    Walk notebook artifacts in order and assign stable section_name using keyword hints
    and monotonic section progression (intro → … → conclusions).
    """
    order = [
        "intro",
        "data_loading",
        "data_check",
        "preprocessing",
        "eda",
        "modeling",
        "evaluation",
        "conclusions",
    ]
    rank = {name: i for i, name in enumerate(order)}
    current = 0

    for art in artifacts:
        if art.artifact_type not in {"markdown_cell", "code_cell"}:
            continue
        src = art.raw_text or ""
        hint = infer_flow_section(src, "markdown" if art.artifact_type == "markdown_cell" else "code")
        meta = art.metadata
        tags = list(meta.get("tags") or [])

        if hint:
            hint_r = rank.get(hint, current)
            current = max(current, hint_r)
            art.section_name = hint
            if hint not in tags:
                tags.append(hint)
        else:
            art.section_name = order[min(current, len(order) - 1)]

        meta["tags"] = tags
        meta["nearby_context"] = {
            "inferred_section": art.section_name,
            "has_plot_hint": bool(_EDA_PAT.search(src) and art.artifact_type == "code_cell"),
        }
