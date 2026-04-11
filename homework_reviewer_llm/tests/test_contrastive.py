import json

from homework_reviewer_llm.contrastive import (
    ContrastiveKind,
    build_bad_review,
    contrastive_record_to_dict,
    messages_rewrite_bad_to_good,
)
from homework_reviewer_llm.schema import NormalizedRecord
from homework_reviewer_llm.sft_format import gold_review_to_output_simple


def _rec() -> NormalizedRecord:
    return NormalizedRecord(
        id="1",
        student_id="s",
        assignment_id="a",
        submission_text="sub " * 30,
        review_text="rev " * 10,
        overall_score=60.0,
    )


def _rec_long_review() -> NormalizedRecord:
    """Длинное ревью для v2 эталона с actionable-рекомендацией (см. gold_review_to_output_v2)."""
    body = "Подробный комментарий ревьюера. " * 8
    return NormalizedRecord(
        id="2",
        student_id="s",
        assignment_id="a",
        submission_text="sub " * 30,
        review_text=body,
        overall_score=70.0,
        revision_history="v0: черновик; v1: правки по замечаниям.",
        student_profile="middle",
    )


def test_build_bad_too_soft_inflates_score() -> None:
    gold = gold_review_to_output_simple(_rec())
    bad = build_bad_review(ContrastiveKind.too_soft, gold)
    assert bad.overall_score >= gold.overall_score
    assert not bad.issues


def test_rewrite_messages_parseable_assistant() -> None:
    rec = _rec()
    msgs = messages_rewrite_bad_to_good(rec, ContrastiveKind.no_justification, output_format="v1")
    assert msgs[-1]["role"] == "assistant"
    data = json.loads(msgs[-1]["content"])
    assert "overall_score" in data


def test_contrastive_dict_id_prefix() -> None:
    d = contrastive_record_to_dict(
        _rec(), mode="inline_warning", kind=ContrastiveKind.too_soft, output_format="v1"
    )
    assert d["id"].startswith("1__contrast__")
    assert len(d["messages"]) == 3


def test_rewrite_v2_assistant_has_hybrid_keys() -> None:
    rec = _rec_long_review()
    msgs = messages_rewrite_bad_to_good(rec, ContrastiveKind.no_justification, output_format="v2")
    data = json.loads(msgs[-1]["content"])
    assert "student_feedback" in data
    assert "reviewer_report" in data
    assert "factor_analysis" in data
    assert data["overall_score"] == 70.0


def test_contrastive_dict_v2_id_contains_format() -> None:
    d = contrastive_record_to_dict(
        _rec_long_review(),
        mode="inline_warning",
        kind=ContrastiveKind.vague_recommendations,
        output_format="v2",
    )
    assert "v2" in d["id"]
    assert d["output_format"] == "v2"
