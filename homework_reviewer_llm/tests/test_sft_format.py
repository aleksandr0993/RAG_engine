import json

from homework_reviewer_llm.schema import NormalizedRecord
from homework_reviewer_llm.sft_format import (
    gold_review_to_output_simple,
    gold_review_to_output_v2,
    record_to_messages,
)


def test_record_to_messages_structure() -> None:
    rec = NormalizedRecord(
        id="1",
        student_id="s",
        assignment_id="a",
        submission_text="sub " * 30,
        review_text="rev " * 10,
        overall_score=77.0,
        assignment_prompt="Do X",
    )
    msgs = record_to_messages(rec)
    assert msgs[0]["role"] == "system"
    assert "Do X" in msgs[1]["content"]
    data = json.loads(msgs[2]["content"])
    assert data["overall_score"] == 77.0


def test_gold_review_has_valid_shape() -> None:
    rec = NormalizedRecord(
        id="1",
        student_id="s",
        assignment_id="a",
        submission_text="sub " * 30,
        review_text="rev " * 10,
        overall_score=77.0,
    )
    out = gold_review_to_output_simple(rec)
    assert out.overall_score == 77.0
    assert out.recommendations


def test_record_to_messages_v2_has_hybrid_keys() -> None:
    rec = NormalizedRecord(
        id="1",
        student_id="s",
        assignment_id="a",
        submission_text="sub " * 30,
        review_text="rev " * 40,
        overall_score=77.0,
        revision_history="v1: fix SQL",
        student_profile="junior",
    )
    msgs = record_to_messages(rec, output_format="v2")
    data = json.loads(msgs[2]["content"])
    assert "student_feedback" in data
    assert "reviewer_report" in data
    assert "factor_analysis" in data


def test_gold_v2_three_factors() -> None:
    rec = NormalizedRecord(
        id="1",
        student_id="s",
        assignment_id="a",
        submission_text="sub " * 30,
        review_text="rev " * 40,
        overall_score=77.0,
    )
    out = gold_review_to_output_v2(rec)
    ids = {f.factor_id for f in out.factor_analysis}
    assert ids == {"submission", "revision_history", "student_profile"}
