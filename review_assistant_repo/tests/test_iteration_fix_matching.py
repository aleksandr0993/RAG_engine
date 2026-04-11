"""Unit tests for iteration fix matching (anchor + evidence disambiguation)."""

from __future__ import annotations

from app.models import ReviewFindingSnapshot
from app.services.iteration_fix_service import (
    evidence_overlap_score,
    group_merged_results_by_code,
    match_merged_to_snapshot,
)


def test_group_merged_preserves_order_and_duplicates():
    merged = [
        {"criterion_code": "a", "anchor_position_idx": 0},
        {"criterion_code": "b", "anchor_position_idx": 1},
        {"criterion_code": "a", "anchor_position_idx": 5},
    ]
    g = group_merged_results_by_code(merged)
    assert [m["anchor_position_idx"] for m in g["a"]] == [0, 5]


def test_match_single_candidate():
    snap = ReviewFindingSnapshot(
        id="s1",
        batch_id="b1",
        criterion_code="intro_exists",
        severity="required",
        status="fail",
        confidence=0.9,
        anchor_position_idx=1,
        generated_comment=None,
        evidence_json=[],
        metadata_json={},
    )
    merged = group_merged_results_by_code(
        [{"criterion_code": "intro_exists", "anchor_position_idx": 1, "status": "pass", "evidence": []}]
    )
    cur, meta = match_merged_to_snapshot(snap, merged)
    assert cur is not None
    assert cur["status"] == "pass"
    assert meta["method"] == "single"


def test_match_picks_nearest_anchor():
    snap = ReviewFindingSnapshot(
        id="s2",
        batch_id="b1",
        criterion_code="dup",
        severity="required",
        status="fail",
        confidence=0.9,
        anchor_position_idx=10,
        generated_comment=None,
        evidence_json=[],
        metadata_json={},
    )
    merged = group_merged_results_by_code(
        [
            {"criterion_code": "dup", "anchor_position_idx": 0, "status": "fail", "evidence": []},
            {"criterion_code": "dup", "anchor_position_idx": 9, "status": "pass", "evidence": []},
            {"criterion_code": "dup", "anchor_position_idx": 50, "status": "warn", "evidence": []},
        ]
    )
    cur, meta = match_merged_to_snapshot(snap, merged)
    assert cur["anchor_position_idx"] == 9
    assert meta["method"] == "multi_disambiguated"
    assert meta["anchor_delta"] == 1


def test_match_tie_breaks_with_evidence_overlap():
    snap = ReviewFindingSnapshot(
        id="s3",
        batch_id="b1",
        criterion_code="x",
        severity="warning",
        status="warn",
        confidence=0.8,
        anchor_position_idx=5,
        generated_comment=None,
        evidence_json=[{"excerpt": "duplicate rows in sales table"}],
        metadata_json={},
    )
    merged = group_merged_results_by_code(
        [
            {
                "criterion_code": "x",
                "anchor_position_idx": 5,
                "status": "pass",
                "evidence": [{"excerpt": "unrelated text about plots"}],
            },
            {
                "criterion_code": "x",
                "anchor_position_idx": 5,
                "status": "pass",
                "evidence": [{"excerpt": "duplicate rows in sales"}],
            },
        ]
    )
    cur, meta = match_merged_to_snapshot(snap, merged)
    ex0 = (cur.get("evidence") or [{}])[0].get("excerpt", "")
    assert "duplicate rows" in ex0
    assert meta["method"] == "multi_disambiguated"
    assert meta.get("evidence_overlap_with_parent", 0) > 0


def test_evidence_overlap_symmetric():
    a = [{"excerpt": "hello world test"}]
    b = [{"excerpt": "hello world"}]
    assert evidence_overlap_score(a, b) > 0
    assert evidence_overlap_score([], []) == 1.0
