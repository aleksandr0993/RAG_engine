from __future__ import annotations

from pathlib import Path

import nbformat
from nbformat.v4 import new_markdown_cell, new_notebook

from app.retrieval.comment_catalog import (
    build_catalog,
    catalog_to_markdown,
    cluster_heuristic,
    detect_alert_color,
    extract_catalog_rows,
    jaccard_similarity,
)
from app.utils.notebook_html import build_notebook_comment_html


def test_detect_alert_color():
    assert detect_alert_color("") == "unknown"
    html = build_notebook_comment_html("T", "body", level="danger")
    assert detect_alert_color(html) == "danger"
    assert detect_alert_color('<div class="alert alert-warning">x') == "warning"
    assert detect_alert_color("class='alert alert-success'") == "success"


def test_jaccard_similarity():
    a = "один два три четыре"
    b = "один два три пять"
    assert jaccard_similarity(a, b) > 0.4
    assert jaccard_similarity("", "") == 1.0
    # Single-letter tokens are ignored by tokenizer → both empty → 1.0
    assert jaccard_similarity("aa bb", "xx yy") == 0.0


def test_cluster_heuristic_merges_similar():
    rows = [
        {"text": "alpha beta gamma delta", "section_name": "eda", "alert_color": "warning"},
        {"text": "alpha beta gamma epsilon", "section_name": "eda", "alert_color": "warning"},
        {"text": "totally different zoo", "section_name": "eda", "alert_color": "warning"},
    ]
    clusters = cluster_heuristic(rows, sim_threshold=0.55)
    assert len(clusters) == 2


def _write_nb(path: Path, cells: list) -> None:
    nb = new_notebook(cells=cells)
    nbformat.write(nb, path)


def test_build_catalog_from_notebooks(tmp_path: Path):
    from app.parsers.notebook import MIDDLE_REVIEWER_MARKER, REVIEWER_MARKER

    c1 = new_markdown_cell("# EDA\n\nисследовательский анализ")
    c2 = new_markdown_cell(
        build_notebook_comment_html("Замечание:", "нужно больше графиков", level="warning")
    )
    c3 = new_markdown_cell(
        f"{MIDDLE_REVIEWER_MARKER}\n\n"
        + build_notebook_comment_html("Ещё:", "нужно больше графиков и подписей", level="warning")
    )
    _write_nb(tmp_path / "a.ipynb", [c1, c2, c3])

    c4 = new_markdown_cell(f"{REVIEWER_MARKER}\n\n" + build_notebook_comment_html("X", "уникальный текст", level="danger"))
    _write_nb(tmp_path / "b.ipynb", [c4])

    cat = build_catalog(
        ipynb_paths=[tmp_path / "a.ipynb", tmp_path / "b.ipynb"],
        source_project="tproj",
        method="heuristic",
        sim_threshold=0.35,
    )
    meta = cat["meta"]
    assert meta["total_notebooks"] == 2
    assert meta["total_source_comments"] >= 2
    assert meta["total_clusters"] >= 1
    assert "note_ru" in meta
    catalog = cat["catalog"]
    assert all("cluster_id" in x for x in catalog)
    assert all("student" not in (x.get("author_roles") or []) for x in catalog)
    md = catalog_to_markdown(cat)
    assert "Справочник" in md
    assert "не является рубрикой" in md.lower() or "рубрик" in md.lower()


def test_extract_include_student(tmp_path: Path):
    from app.parsers.notebook import REVIEWER_MARKER, STUDENT_MARKER

    cells = [
        new_markdown_cell("код студента длинный " * 5),
        new_markdown_cell(f"{STUDENT_MARKER}\n\nвопрос?"),
        new_markdown_cell(f"{REVIEWER_MARKER}\n\n" + build_notebook_comment_html("R", "ok", level="success")),
    ]
    _write_nb(tmp_path / "s.ipynb", cells)
    rows, students = extract_catalog_rows([tmp_path / "s.ipynb"], source_project="p", include_student_samples=True)
    assert rows
    assert students
    assert any("вопрос" in s["text"] for s in students)


def test_tfidf_kmeans_smoke():
    pytest = __import__("pytest")
    pytest.importorskip("sklearn.cluster")
    from app.retrieval.comment_catalog import cluster_tfidf_kmeans

    rows = [
        {
            "text": f"метрика roc auc precision вариант {i}",
            "section_name": "modeling",
            "alert_color": "warning",
        }
        for i in range(5)
    ]
    clusters = cluster_tfidf_kmeans(rows, n_clusters=2, auto_k_method="fixed")
    assert len(clusters) >= 1
    assert sum(len(c["members"]) for c in clusters) == 5
