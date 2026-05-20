from __future__ import annotations

from app.services.student_assistant import KnowledgeChunk, rank_knowledge_chunks


def test_project_boost_prefers_project_when_text_identical():
    chunks = [
        KnowledgeChunk("c1", "hello world example", "course_base", "course:faq"),
        KnowledgeChunk("p1", "hello world example", "project_doc", "project:sql"),
    ]
    ranked = rank_knowledge_chunks("hello", chunks, project_boost=2.0)
    assert ranked[0][0].source_kind == "project_doc"


def test_rank_orders_by_relevance():
    chunks = [
        KnowledgeChunk("a", "котики и собаки", "course_base", "c1"),
        KnowledgeChunk("b", "sql select from metrics ctr", "project_doc", "c2"),
    ]
    ranked = rank_knowledge_chunks("ctr metrics", chunks, project_boost=1.0)
    assert "metrics" in ranked[0][0].text


def test_rank_can_use_notebook_memory_and_external_sources():
    chunks = [
        KnowledgeChunk("m", "roc auc выбран для несбалансированной классификации", "notebook_memory", "notebook_memory:key_findings"),
        KnowledgeChunk("e", "roc auc sklearn docs", "external_web", "sklearn docs", url="https://example.test"),
    ]
    ranked = rank_knowledge_chunks("roc auc классификация", chunks, project_boost=1.0)
    assert ranked[0][0].source_kind in {"notebook_memory", "external_web"}
