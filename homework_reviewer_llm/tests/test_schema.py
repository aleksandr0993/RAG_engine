import json

import pytest

from homework_reviewer_llm.schema import (
    IssueItem,
    parse_review_json,
    parse_review_json_v2,
    try_parse_review_json,
)


def test_parse_review_json_ok() -> None:
    raw = json.dumps(
        {
            "strengths": [{"text": "Хорошо"}],
            "issues": [{"text": "Мало тестов", "severity": "medium"}],
            "recommendations": [{"text": "Добавить pytest", "actionable": True}],
            "score_justification": "Неплохо",
            "overall_score": 80.0,
            "rubric_scores": {"a": 1},
        }
    )
    r = parse_review_json(raw)
    assert r.overall_score == 80.0


def test_parse_fenced_code_block() -> None:
    inner = '{"strengths":[],"issues":[],"recommendations":[],"score_justification":"x","overall_score":1}'
    raw = "```json\n" + inner + "\n```"
    r = parse_review_json(raw)
    assert r.overall_score == 1.0


def test_try_parse_invalid() -> None:
    pred, err = try_parse_review_json("not json")
    assert pred is None
    assert err is not None


def test_severity_validation() -> None:
    with pytest.raises(Exception):
        IssueItem(text="x", severity="huge")


def test_parse_review_json_v2_minimal() -> None:
    raw = """
    {
      "student_feedback": {
        "summary": "Итог для студента",
        "strengths": [{"text": "Плюс"}],
        "issues": [{"text": "Минус", "severity": "low"}],
        "recommendations": [{"text": "Шаг 1", "actionable": true}]
      },
      "reviewer_report": {
        "summary": "Резюме для ревьюера достаточно длинное",
        "risk_assessment": "Риски описаны здесь подробно для проверки",
        "score_justification": "Обоснование оценки достаточно длинное для теста guardrails и метрик"
      },
      "factor_analysis": [
        {"factor_id": "submission", "how_used": "Основа"},
        {"factor_id": "revision_history", "how_used": "Нет данных"},
        {"factor_id": "student_profile", "how_used": "Нет данных"}
      ],
      "overall_score": 70
    }
    """
    out = parse_review_json_v2(raw)
    assert out.overall_score == 70.0
    assert len(out.factor_analysis) == 3
