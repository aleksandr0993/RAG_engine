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


def test_project_training_excludes_student_and_wildcard_criterion(monkeypatch, tmp_path):
    monkeypatch.setenv("ENABLE_RETRIEVAL", "true")
    monkeypatch.delenv("REVIEW_EXAMPLES_PATH", raising=False)
    monkeypatch.delenv("ENABLE_REVIEWER_REFERENCE_EXAMPLES", raising=False)
    monkeypatch.setenv("ENABLE_PROJECT_REVIEW_TRAINING", "true")
    monkeypatch.setenv("PROJECT_REVIEW_TRAINING_PATH", str(tmp_path / "pt.jsonl"))

    from app.config import get_settings
    from app.retrieval.local_examples import LocalFileRetrievalBackend

    get_settings.cache_clear()
    rows = [
        {
            "example_id": "s1",
            "criterion_code": "",
            "text": "student says hi",
            "author_role": "student",
            "source_project": "p",
            "source_notebook": "a.ipynb",
            "student_context": "",
            "tags": [],
        },
        {
            "example_id": "r1",
            "criterion_code": "",
            "text": "reviewer comment unique phrase",
            "author_role": "reviewer",
            "source_project": "p",
            "source_notebook": "a.ipynb",
            "student_context": "ctx",
            "tags": [],
        },
    ]
    (tmp_path / "pt.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    b = LocalFileRetrievalBackend(path=None)
    got = b.retrieve(query="nomatch", criterion_code="ANY_CODE", limit=3)
    assert len(got) == 1
    assert got[0].author_role == "reviewer"
    assert "unique phrase" in got[0].text


def test_project_training_diversity_two_notebooks(monkeypatch, tmp_path):
    monkeypatch.setenv("ENABLE_RETRIEVAL", "true")
    monkeypatch.setenv("REVIEW_EXAMPLES_PATH", str(tmp_path / "g.jsonl"))
    monkeypatch.setenv("ENABLE_PROJECT_REVIEW_TRAINING", "true")
    pt_dir = tmp_path / "pt"
    pt_dir.mkdir()

    from app.config import get_settings
    from app.retrieval.local_examples import LocalFileRetrievalBackend

    get_settings.cache_clear()
    monkeypatch.setenv("PROJECT_REVIEW_TRAINING_PATH", str(pt_dir))

    (tmp_path / "g.jsonl").write_text(
        json.dumps(
            {
                "example_id": "g1",
                "criterion_code": "C1",
                "text": "general zed match",
                "tags": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (pt_dir / "n1.jsonl").write_text(
        json.dumps(
            {
                "example_id": "p1",
                "criterion_code": "C1",
                "text": "nb1 reviewer",
                "author_role": "reviewer",
                "source_notebook": "one.ipynb",
                "source_project": "p",
                "tags": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (pt_dir / "n2.jsonl").write_text(
        json.dumps(
            {
                "example_id": "p2",
                "criterion_code": "C1",
                "text": "nb2 middle",
                "author_role": "middle_reviewer",
                "source_notebook": "two.ipynb",
                "source_project": "p",
                "tags": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    b = LocalFileRetrievalBackend()
    got = b.retrieve(query="zed", criterion_code="C1", limit=3)
    assert len(got) == 3
    nbs = {e.source_notebook for e in got if e.source_notebook}
    assert "one.ipynb" in nbs and "two.ipynb" in nbs
    assert any("zed" in e.text.lower() for e in got)
