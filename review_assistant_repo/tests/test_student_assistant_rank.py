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
