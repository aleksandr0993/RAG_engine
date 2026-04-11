from homework_reviewer_llm.guardrails import validate_review_output, validate_review_output_v2
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


def test_justification_too_short_fails() -> None:
    out = ReviewOutput(
        strengths=[],
        issues=[],
        recommendations=[RecommendationItem(text="x", actionable=True)],
        score_justification="коротко",
        overall_score=5.0,
    )
    r = validate_review_output(out, min_justification_len=40)
    assert not r.ok
    assert any("score_justification" in e for e in r.errors)


def test_high_severity_without_quote_fails() -> None:
    out = ReviewOutput(
        strengths=[],
        issues=[IssueItem(text="Критично", severity="high")],
        recommendations=[],
        score_justification="x" * 50,
        overall_score=1.0,
    )
    r = validate_review_output(out)
    assert not r.ok


def test_strong_claim_without_quote_fails() -> None:
    out = ReviewOutput(
        strengths=[],
        issues=[IssueItem(text="Это полностью неверно по условию.", severity="low")],
        recommendations=[],
        score_justification="x" * 50,
        overall_score=1.0,
    )
    r = validate_review_output(out)
    assert not r.ok


def _ok_v2() -> ReviewOutputV2:
    return ReviewOutputV2(
        student_feedback=StudentFeedback(
            summary="Итог",
            strengths=[StrengthItem(text="s")],
            issues=[IssueItem(text="i", severity="low")],
            recommendations=[RecommendationItem(text="r", actionable=True)],
        ),
        reviewer_report=ReviewerReport(
            summary="Резюме для ревьюера",
            risk_assessment="оценка рисков " * 4,
            score_justification="обоснование " * 8,
        ),
        factor_analysis=[
            FactorAnalysisItem(factor_id="submission", how_used="u1"),
            FactorAnalysisItem(factor_id="revision_history", how_used="u2"),
            FactorAnalysisItem(factor_id="student_profile", how_used="u3"),
        ],
        overall_score=10.0,
    )


def test_v2_ok() -> None:
    assert validate_review_output_v2(_ok_v2()).ok


def test_v2_missing_factor_fails() -> None:
    o = _ok_v2()
    o = o.model_copy(update={"factor_analysis": o.factor_analysis[:2]})
    r = validate_review_output_v2(o)
    assert not r.ok


def test_v2_no_actionable_fails() -> None:
    o = _ok_v2()
    recs = list(o.student_feedback.recommendations)
    recs[0] = recs[0].model_copy(update={"actionable": False})
    sf = o.student_feedback.model_copy(update={"recommendations": recs})
    o2 = o.model_copy(update={"student_feedback": sf})
    r = validate_review_output_v2(o2)
    assert not r.ok
