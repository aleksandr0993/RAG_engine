from __future__ import annotations

from app.llm.types import LLMCallResult
from app.services.finding_policy import (
    apply_low_confidence_and_quality_policy,
    apply_required_fail_evidence_gate,
    build_manual_review_summary,
    coerce_source_stage_metadata,
    normalize_source_stage,
)


class FakeGateLLM:
    is_available = True

    def __init__(self, text: str = "", *, ok: bool = True, error: str | None = None):
        self.text = text
        self.ok = ok
        self.error = error
        self.messages = []
        self.model = None
        self.max_tokens = None

    def chat(self, messages, temperature=0.2, *, model=None, max_tokens=None):
        self.messages = messages
        self.model = model
        self.max_tokens = max_tokens
        return LLMCallResult(ok=self.ok, text=self.text, error=self.error, model=model or "fake")


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


def test_required_fail_without_evidence_llm_pass_converts_to_pass():
    llm = FakeGateLLM(
        '{"status":"pass","confidence":0.91,"anchor_position_idx":5,'
        '"evidence_quote":"top_platforms = df.platform.value_counts().head(7)","reason":"top 7 exists"}'
    )
    out = apply_required_fail_evidence_gate(
        status="fail",
        severity="required",
        confidence=0.96,
        metadata={},
        criterion={
            "code": "games_top7_platforms",
            "title": "Top 7 platforms",
            "description": "Find seven platforms",
            "severity": "required",
            "detection_mode": "hybrid",
        },
        artifacts=[
            {
                "artifact_type": "code_cell",
                "position_idx": 5,
                "normalized_text": "top_platforms = df.platform.value_counts().head(7)",
            }
        ],
        evidence=[],
        anchor_position_idx=None,
        enabled=True,
        llm_service=llm,
        enable_llm_required_fail_verification=True,
        llm_required_fail_verification_model="gpt-test",
        llm_required_fail_max_output_tokens=321,
        failed_comment_text="Выдели топ-7 платформ.",
    )

    assert out.status == "pass"
    assert out.anchor_position_idx == 5
    assert out.evidence[0]["source"] == "llm_required_fail_verification"
    assert out.metadata["policy_whole_notebook_verification"] == "llm_pass_found"
    assert out.metadata["policy_llm_required_fail_verification_used"] is True
    assert llm.model == "gpt-test"
    assert llm.max_tokens == 321
    assert "untrusted content" in llm.messages[0]["content"]


def test_required_fail_without_evidence_llm_pass_without_evidence_downgrades():
    llm = FakeGateLLM('{"status":"pass","confidence":0.95,"anchor_position_idx":5,"evidence_quote":"","reason":"looks ok"}')
    out = apply_required_fail_evidence_gate(
        status="fail",
        severity="required",
        confidence=0.96,
        metadata={},
        criterion={"code": "x", "severity": "required", "detection_mode": "hybrid"},
        artifacts=[{"artifact_type": "code_cell", "position_idx": 5, "normalized_text": "df.head()"}],
        evidence=[],
        anchor_position_idx=None,
        enabled=True,
        llm_service=llm,
        enable_llm_required_fail_verification=True,
    )

    assert out.status == "warn"
    assert out.metadata["policy_whole_notebook_verification"] == "llm_not_found_downgraded"
    assert out.metadata["policy_llm_required_fail_verification_status"] == "pass"


def test_required_fail_without_evidence_llm_uncertain_or_error_downgrades():
    uncertain = apply_required_fail_evidence_gate(
        status="fail",
        severity="required",
        confidence=0.96,
        metadata={},
        criterion={"code": "x", "severity": "required", "detection_mode": "hybrid"},
        artifacts=[{"artifact_type": "code_cell", "position_idx": 1, "normalized_text": "df.head()"}],
        evidence=[],
        anchor_position_idx=None,
        enabled=True,
        llm_service=FakeGateLLM('{"status":"uncertain","confidence":0.5,"evidence_quote":"","reason":"unclear"}'),
        enable_llm_required_fail_verification=True,
    )
    error = apply_required_fail_evidence_gate(
        status="fail",
        severity="required",
        confidence=0.96,
        metadata={},
        criterion={"code": "x", "severity": "required", "detection_mode": "hybrid"},
        artifacts=[{"artifact_type": "code_cell", "position_idx": 1, "normalized_text": "df.head()"}],
        evidence=[],
        anchor_position_idx=None,
        enabled=True,
        llm_service=FakeGateLLM(ok=False, error="boom"),
        enable_llm_required_fail_verification=True,
    )

    assert uncertain.status == "warn"
    assert uncertain.metadata["policy_whole_notebook_verification"] == "llm_not_found_downgraded"
    assert error.status == "warn"
    assert error.metadata["policy_whole_notebook_verification"] == "llm_unavailable_downgraded"


def test_required_fail_without_evidence_llm_flag_off_preserves_deterministic_downgrade():
    llm = FakeGateLLM('{"status":"pass","confidence":0.99,"evidence_quote":"df.head()","reason":"ok"}')
    out = apply_required_fail_evidence_gate(
        status="fail",
        severity="required",
        confidence=0.96,
        metadata={},
        criterion={"code": "x", "severity": "required", "detection_mode": "hybrid"},
        artifacts=[{"artifact_type": "code_cell", "position_idx": 1, "normalized_text": "df.head()"}],
        evidence=[],
        anchor_position_idx=None,
        enabled=True,
        llm_service=llm,
        enable_llm_required_fail_verification=False,
    )

    assert out.status == "warn"
    assert out.metadata["policy_whole_notebook_verification"] == "no_evidence_downgraded"
    assert llm.messages == []


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
