from __future__ import annotations

from app.services.finding_policy import (
    apply_low_confidence_and_quality_policy,
    build_manual_review_summary,
    coerce_source_stage_metadata,
    normalize_source_stage,
)


def test_normalize_source_stage_enum():
    assert normalize_source_stage("rule") == "rule"
    assert normalize_source_stage(None, "hybrid") == "semantic"
    assert normalize_source_stage("bogus") == "unspecified"


def test_coerce_metadata_stashes_raw_unknown():
    meta = coerce_source_stage_metadata({"source_stage": "weird_stage"}, "rule")
    assert meta["source_stage"] == "semantic"
    assert meta.get("source_stage_raw") == "weird_stage"


def test_low_confidence_downgrades_required_fail():
    out = apply_low_confidence_and_quality_policy(
        status="fail",
        severity="required",
        confidence=0.2,
        metadata={},
        criterion_code="x",
        min_confidence_for_required_fail=0.55,
        enabled=True,
    )
    assert out.status == "warn"
    assert out.metadata.get("policy_low_confidence_downgrade") is True
    assert out.metadata.get("manual_review_suggested") is True


def test_required_unknown_flags_manual_review():
    out = apply_low_confidence_and_quality_policy(
        status="unknown",
        severity="required",
        confidence=None,
        metadata={},
        criterion_code="y",
        min_confidence_for_required_fail=0.55,
        enabled=True,
    )
    assert out.status == "unknown"
    assert out.metadata.get("manual_review_suggested") is True


def test_build_manual_review_summary_merges_reasons():
    merged = [
        {"metadata": {"manual_review_reasons": ["a:1"], "manual_review_suggested": True}},
        {"metadata": {"manual_review_reasons": ["b:2"]}},
    ]
    s = build_manual_review_summary(merged)
    assert s["manual_review_needed"] is True
    assert "a:1" in s["manual_review_reasons"]
