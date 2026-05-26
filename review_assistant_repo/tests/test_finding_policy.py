from __future__ import annotations

from app.services.finding_policy import (
    apply_low_confidence_and_quality_policy,
    apply_required_fail_evidence_gate,
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


def test_required_fail_without_evidence_downgrades_to_warn():
    out = apply_required_fail_evidence_gate(
        status="fail",
        severity="required",
        confidence=0.96,
        metadata={},
        criterion={
            "code": "x",
            "severity": "required",
            "detection_mode": "rule",
            "rule": {"artifact_types": ["code_cell"], "patterns_all": ["missing_token"]},
        },
        artifacts=[{"artifact_type": "code_cell", "position_idx": 1, "normalized_text": "df.head()"}],
        evidence=[],
        anchor_position_idx=None,
        enabled=True,
    )

    assert out.status == "warn"
    assert out.metadata["policy_required_fail_without_evidence"] is True
    assert out.metadata["policy_whole_notebook_verification"] == "no_evidence_downgraded"
    assert out.metadata["manual_review_suggested"] is True
    assert "x:required_fail_without_evidence" in out.metadata["manual_review_reasons"]


def test_required_fail_without_evidence_can_be_recovered_by_whole_notebook_rule_match():
    out = apply_required_fail_evidence_gate(
        status="fail",
        severity="required",
        confidence=0.96,
        metadata={},
        criterion={
            "code": "games_top7_platforms",
            "severity": "required",
            "detection_mode": "rule",
            "rule": {
                "artifact_types": ["code_cell"],
                "acceptable_patterns": [
                    {
                        "patterns_any": ["value_counts", "groupby"],
                        "patterns_all": ["platform", "nlargest(7"],
                    }
                ],
            },
        },
        artifacts=[
            {
                "artifact_type": "code_cell",
                "position_idx": 9,
                "normalized_text": "top_platforms = df['platform'].value_counts().nlargest(7).index",
            }
        ],
        evidence=[],
        anchor_position_idx=None,
        enabled=True,
    )

    assert out.status == "pass"
    assert out.anchor_position_idx == 9
    assert out.evidence
    assert out.metadata["policy_whole_notebook_verification"] == "pass_found"


def test_required_fail_with_evidence_is_not_downgraded():
    out = apply_required_fail_evidence_gate(
        status="fail",
        severity="required",
        confidence=0.96,
        metadata={},
        criterion={"code": "x", "severity": "required", "detection_mode": "rule", "rule": {}},
        artifacts=[],
        evidence=[{"excerpt": "problem evidence"}],
        anchor_position_idx=3,
        enabled=True,
    )

    assert out.status == "fail"
    assert out.anchor_position_idx == 3
    assert out.metadata == {}


def test_optional_fail_without_evidence_is_not_changed():
    out = apply_required_fail_evidence_gate(
        status="fail",
        severity="optional",
        confidence=0.96,
        metadata={},
        criterion={"code": "x", "severity": "optional", "detection_mode": "rule", "rule": {}},
        artifacts=[],
        evidence=[],
        anchor_position_idx=None,
        enabled=True,
    )

    assert out.status == "fail"
    assert out.metadata == {}


def test_build_manual_review_summary_merges_reasons():
    merged = [
        {"metadata": {"manual_review_reasons": ["a:1"], "manual_review_suggested": True}},
        {"metadata": {"manual_review_reasons": ["b:2"]}},
    ]
    s = build_manual_review_summary(merged)
    assert s["manual_review_needed"] is True
    assert "a:1" in s["manual_review_reasons"]
