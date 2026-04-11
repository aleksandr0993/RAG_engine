from __future__ import annotations

import json

import pytest


@pytest.fixture(autouse=True)
def _clear_caches():
    from app.config import get_settings
    from app.retrieval.local_examples import get_retrieval_backend

    get_settings.cache_clear()
    get_retrieval_backend.cache_clear()
    yield
    get_settings.cache_clear()
    get_retrieval_backend.cache_clear()


def test_project_training_filters_by_source_project(monkeypatch, tmp_path):
    monkeypatch.setenv("ENABLE_RETRIEVAL", "true")
    monkeypatch.delenv("REVIEW_EXAMPLES_PATH", raising=False)
    monkeypatch.setenv("ENABLE_PROJECT_REVIEW_TRAINING", "true")
    monkeypatch.setenv("PROJECT_REVIEW_TRAINING_PATH", str(tmp_path / "pt.jsonl"))

    from app.config import get_settings
    from app.retrieval.local_examples import LocalFileRetrievalBackend

    get_settings.cache_clear()
    rows = [
        {
            "example_id": "w1",
            "criterion_code": "",
            "text": "wrong project",
            "author_role": "reviewer",
            "source_project": "other",
            "source_notebook": "a.ipynb",
            "tags": [],
        },
        {
            "example_id": "ok",
            "criterion_code": "",
            "text": "match project",
            "author_role": "reviewer",
            "source_project": "wanted",
            "source_notebook": "b.ipynb",
            "tags": [],
        },
        {
            "example_id": "wild",
            "criterion_code": "",
            "text": "wildcard project",
            "author_role": "reviewer",
            "source_project": "",
            "source_notebook": "c.ipynb",
            "tags": [],
        },
    ]
    (tmp_path / "pt.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    b = LocalFileRetrievalBackend(path=None)
    got = b.retrieve("q", "C1", limit=5, filter_source_project="wanted")
    texts = {x.text for x in got}
    assert "match project" in texts
    assert "wildcard project" in texts
    assert "wrong project" not in texts
    assert all(x.source_kind == "project_training" for x in got)


def test_project_training_sorts_by_section_then_diverse(monkeypatch, tmp_path):
    monkeypatch.setenv("ENABLE_RETRIEVAL", "true")
    monkeypatch.delenv("REVIEW_EXAMPLES_PATH", raising=False)
    monkeypatch.setenv("ENABLE_PROJECT_REVIEW_TRAINING", "true")
    monkeypatch.setenv("PROJECT_REVIEW_TRAINING_PATH", str(tmp_path / "pt.jsonl"))

    from app.config import get_settings
    from app.retrieval.local_examples import LocalFileRetrievalBackend

    get_settings.cache_clear()
    rows = [
        {
            "example_id": "other_sec",
            "criterion_code": "",
            "text": "other section body",
            "author_role": "reviewer",
            "source_project": "p",
            "source_notebook": "n1.ipynb",
            "section_name": "hypothesis",
            "tags": [],
        },
        {
            "example_id": "eda_first",
            "criterion_code": "",
            "text": "eda match first",
            "author_role": "reviewer",
            "source_project": "p",
            "source_notebook": "n2.ipynb",
            "section_name": "eda",
            "tags": [],
        },
        {
            "example_id": "eda_second",
            "criterion_code": "",
            "text": "eda match second",
            "author_role": "middle_reviewer",
            "source_project": "p",
            "source_notebook": "n3.ipynb",
            "section_name": "eda",
            "tags": [],
        },
    ]
    (tmp_path / "pt.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    b = LocalFileRetrievalBackend(path=None)
    got = b.retrieve("q", "X", limit=2, filter_section_name="eda")
    assert len(got) == 2
    assert got[0].section_name == "eda"
    assert got[1].section_name == "eda"
    assert "hypothesis" not in {x.section_name for x in got}
