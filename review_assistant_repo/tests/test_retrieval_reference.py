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


def test_retrieval_general_substring_only(monkeypatch, tmp_path):
    monkeypatch.setenv("ENABLE_RETRIEVAL", "true")
    monkeypatch.setenv("REVIEW_EXAMPLES_PATH", str(tmp_path / "g.jsonl"))
    monkeypatch.delenv("ENABLE_REVIEWER_REFERENCE_EXAMPLES", raising=False)
    monkeypatch.delenv("REVIEWER_REFERENCE_EXAMPLES_PATH", raising=False)

    from app.config import get_settings
    from app.retrieval.local_examples import LocalFileRetrievalBackend

    get_settings.cache_clear()
    (tmp_path / "g.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {"example_id": "1", "criterion_code": "NB_A", "text": "alpha beta comment", "tags": []}
                ),
                json.dumps(
                    {"example_id": "2", "criterion_code": "NB_A", "text": "gamma only", "tags": []}
                ),
            ]
        ),
        encoding="utf-8",
    )
    b = LocalFileRetrievalBackend()
    got = b.retrieve(query="alpha", criterion_code="NB_A", limit=3)
    assert len(got) == 1
    assert got[0].text == "alpha beta comment"
    assert not got[0].from_reviewer_reference


def test_retrieval_merges_reviewer_reference_without_query_match(monkeypatch, tmp_path):
    monkeypatch.setenv("ENABLE_RETRIEVAL", "true")
    monkeypatch.setenv("REVIEW_EXAMPLES_PATH", str(tmp_path / "g.jsonl"))
    monkeypatch.setenv("ENABLE_REVIEWER_REFERENCE_EXAMPLES", "true")
    monkeypatch.setenv("REVIEWER_REFERENCE_EXAMPLES_PATH", str(tmp_path / "r.jsonl"))

    from app.config import get_settings
    from app.retrieval.local_examples import LocalFileRetrievalBackend

    get_settings.cache_clear()
    (tmp_path / "g.jsonl").write_text(
        json.dumps({"example_id": "g1", "criterion_code": "NB_A", "text": "match query zed", "tags": ["corpus"]})
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "r.jsonl").write_text(
        json.dumps(
            {
                "example_id": "sr1",
                "criterion_code": "NB_A",
                "text": "Senior phrasing without zed keyword",
                "tags": ["colab_ref"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    b = LocalFileRetrievalBackend()
    got = b.retrieve(query="zed", criterion_code="NB_A", limit=3)
    assert len(got) == 2
    assert got[0].from_reviewer_reference
    assert "Senior phrasing" in got[0].text
    assert not got[1].from_reviewer_reference
    assert "zed" in got[1].text.lower()


def test_retrieval_reference_only_file(monkeypatch, tmp_path):
    monkeypatch.setenv("ENABLE_RETRIEVAL", "true")
    monkeypatch.delenv("REVIEW_EXAMPLES_PATH", raising=False)
    monkeypatch.setenv("ENABLE_REVIEWER_REFERENCE_EXAMPLES", "true")
    monkeypatch.setenv("REVIEWER_REFERENCE_EXAMPLES_PATH", str(tmp_path / "r.jsonl"))

    from app.config import get_settings
    from app.retrieval.local_examples import LocalFileRetrievalBackend

    get_settings.cache_clear()
    (tmp_path / "r.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"example_id": "a", "criterion_code": "X", "text": "first", "tags": []}),
                json.dumps({"example_id": "b", "criterion_code": "X", "text": "second", "tags": []}),
            ]
        ),
        encoding="utf-8",
    )
    b = LocalFileRetrievalBackend(path=None)
    got = b.retrieve(query="nomatchsubstring", criterion_code="X", limit=2)
    assert len(got) == 2
    assert all(x.from_reviewer_reference for x in got)
