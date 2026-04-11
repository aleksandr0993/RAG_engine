from homework_reviewer_llm.metrics import evaluate_pairs, evaluate_pairs_v2
from homework_reviewer_llm.schema import (
    FactorAnalysisItem,
    IssueItem,
    RecommendationItem,
    ReviewOutput,
    ReviewOutputV2,
    ReviewerReport,
    StrengthItem,
    StudentFeedback,
)


def test_evaluate_perfect() -> None:
    gold = ReviewOutput(
        strengths=[],
        issues=[],
        recommendations=[{"text": "r", "actionable": True}],
        score_justification="j",
        overall_score=80.0,
        rubric_scores={"x": 1.0},
    )
    pred_raw = gold.model_dump_json(exclude_none=True)
    m = evaluate_pairs([gold], [pred_raw])
    s = m.summary()
    assert s["json_valid_rate"] == 1.0
    assert s["score_mae"] == 0.0


def test_evaluate_mae() -> None:
    gold = ReviewOutput(
        strengths=[],
        issues=[],
        recommendations=[],
        score_justification="j",
        overall_score=100.0,
    )
    pred = gold.model_copy(update={"overall_score": 90.0})
    m = evaluate_pairs([gold], [pred.model_dump_json(exclude_none=True)])
    assert m.summary()["score_mae"] == 10.0


def test_invalid_pred() -> None:
    gold = ReviewOutput(
        strengths=[],
        issues=[],
        recommendations=[],
        score_justification="j",
        overall_score=1.0,
    )
    m = evaluate_pairs([gold], ["not-json"])
    s = m.summary()
    assert s["json_valid_rate"] == 0.0
    assert s["score_mae"] is None


def _v2_dummy() -> ReviewOutputV2:
    sf = StudentFeedback(
        summary="Краткое резюме для студента по работе",
        strengths=[StrengthItem(text="x")],
        issues=[IssueItem(text="y", severity="low")],
        recommendations=[RecommendationItem(text="z", actionable=True)],
    )
    rr = ReviewerReport(
        summary="Внутреннее резюме ревьюера по критичности",
        risk_assessment="risks " * 5,
        score_justification="just " * 10,
    )
    fa = [
        FactorAnalysisItem(factor_id="submission", how_used="a"),
        FactorAnalysisItem(factor_id="revision_history", how_used="b"),
        FactorAnalysisItem(factor_id="student_profile", how_used="c"),
    ]
    return ReviewOutputV2(
        student_feedback=sf,
        reviewer_report=rr,
        factor_analysis=fa,
        overall_score=50.0,
    )


def test_evaluate_v2_factor_coverage() -> None:
    gold = _v2_dummy()
    pred_raw = gold.model_dump_json(exclude_none=True)
    m = evaluate_pairs_v2([gold], [pred_raw])
    s = m.summary()
    assert s["format"] == "v2"
    assert s["factor_coverage_rate"] == 1.0
    assert s["dual_audience_completeness"] == 1.0
