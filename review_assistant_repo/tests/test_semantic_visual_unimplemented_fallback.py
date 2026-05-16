"""Unknown-task fallbacks for semantic/visual analyzers (documented in README)."""

from __future__ import annotations

from app.analyzers.semantic import SemanticAnalyzer
from app.analyzers.visual import VisualAnalyzer


def test_semantic_unknown_task_returns_unknown_not_implemented() -> None:
    criterion = {"severity": "recommended", "code": "t_sem_x"}
    out = SemanticAnalyzer().check("__fixture_unknown_semantic_task__", [], criterion)
    assert out["status"] == "unknown"
    meta = out.get("metadata") or {}
    assert meta.get("note") == "not implemented"
    assert meta.get("source_stage") == "semantic"


def test_visual_unknown_task_returns_unknown_not_implemented() -> None:
    criterion = {"severity": "recommended", "code": "t_vis_x"}
    out = VisualAnalyzer().check("__fixture_unknown_visual_task__", [], criterion)
    assert out["status"] == "unknown"
    meta = out.get("metadata") or {}
    assert meta.get("note") == "not implemented"
    assert meta.get("source_stage") == "visual"
