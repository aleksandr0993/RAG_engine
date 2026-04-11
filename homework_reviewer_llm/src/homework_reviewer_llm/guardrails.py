"""Пост-проверка структурированного ревью v1 и гибридного ответа v2."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from homework_reviewer_llm.schema import FACTOR_IDS, ReviewOutput, ReviewOutputV2

# Категоричные формулировки без цитаты — эвристика (RU).
_STRONG_CLAIM_PATTERNS = re.compile(
    r"(полностью неверно|абсолютно неправ|однозначно ошиб|"
    r"нигде не указано|ни слова о|совсем не|вообще не сделал|"
    r"полное отсутствие|не соответствует заданию полностью)",
    re.IGNORECASE,
)


@dataclass
class GuardrailResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate_review_output(
    out: ReviewOutput,
    *,
    min_justification_len: int = 40,
    require_quote_for_high_severity: bool = True,
    check_strong_claims_without_quote: bool = True,
) -> GuardrailResult:
    """
    Проверки v1:
    - обязательное обоснование оценки (длина score_justification);
    - для issues с severity=high желательна evidence_quote;
    - эвристика: сильные утверждения в тексте issues/strengths без evidence_quote.
    """
    errors: list[str] = []
    warnings: list[str] = []

    sj = out.score_justification.strip()
    if len(sj) < min_justification_len:
        errors.append(
            f"score_justification слишком короткий ({len(sj)} симв., нужно ≥ {min_justification_len})"
        )

    if not out.recommendations:
        warnings.append("нет рекомендаций")

    for i, issue in enumerate(out.issues):
        if require_quote_for_high_severity and issue.severity == "high":
            q = (issue.evidence_quote or "").strip()
            if len(q) < 3:
                errors.append(f"issues[{i}]: severity=high без цитаты (evidence_quote)")

    if check_strong_claims_without_quote:
        for i, issue in enumerate(out.issues):
            if _STRONG_CLAIM_PATTERNS.search(issue.text) and not (issue.evidence_quote or "").strip():
                errors.append(
                    f"issues[{i}]: категоричная формулировка без evidence_quote"
                )
        for i, st in enumerate(out.strengths):
            if _STRONG_CLAIM_PATTERNS.search(st.text) and not (st.evidence_quote or "").strip():
                warnings.append(
                    f"strengths[{i}]: сильная формулировка без evidence_quote"
                )

    return GuardrailResult(ok=len(errors) == 0, errors=errors, warnings=warnings)


def validate_review_output_v2(
    out: ReviewOutputV2,
    *,
    min_reviewer_justification_len: int = 40,
    min_risk_len: int = 25,
    require_actionable_student_step: bool = True,
    check_strong_claims_without_quote: bool = True,
) -> GuardrailResult:
    """
    Проверки v2:
    - полнота factor_analysis по factor_id (все три фактора);
    - блоки student_feedback и reviewer_report непустые по смыслу;
    - хотя бы одна actionable-рекомендация для студента;
    - reviewer_report: risk_assessment и score_justification достаточной длины.
    """
    errors: list[str] = []
    warnings: list[str] = []

    ids_found = {item.factor_id for item in out.factor_analysis}
    missing = FACTOR_IDS - ids_found
    if missing:
        errors.append(f"factor_analysis: отсутствуют factor_id: {sorted(missing)}")

    if not out.student_feedback.summary.strip():
        errors.append("student_feedback.summary пустой")

    rr = out.reviewer_report
    if len(rr.summary.strip()) < 10:
        errors.append("reviewer_report.summary слишком короткий")
    if len(rr.risk_assessment.strip()) < min_risk_len:
        errors.append(
            f"reviewer_report.risk_assessment слишком короткий (< {min_risk_len} симв.)"
        )
    if len(rr.score_justification.strip()) < min_reviewer_justification_len:
        errors.append(
            "reviewer_report.score_justification слишком короткий "
            f"(< {min_reviewer_justification_len} симв.)"
        )

    if require_actionable_student_step:
        recs = out.student_feedback.recommendations
        if not any(r.actionable for r in recs):
            errors.append(
                "student_feedback: нет ни одной рекомендации с actionable=true"
            )

    if check_strong_claims_without_quote:
        for i, issue in enumerate(out.student_feedback.issues):
            if _STRONG_CLAIM_PATTERNS.search(issue.text) and not (issue.evidence_quote or "").strip():
                errors.append(
                    f"student_feedback.issues[{i}]: категоричная формулировка без evidence_quote"
                )

    return GuardrailResult(ok=len(errors) == 0, errors=errors, warnings=warnings)


def validate_raw_by_format(
    raw: str,
    *,
    output_format: str,
) -> tuple[GuardrailResult, str | None]:
    """Парсит raw и применяет guardrails v1 или v2. Возвращает (result, parse_error)."""
    from homework_reviewer_llm.schema import try_parse_review_json, try_parse_review_json_v2

    if output_format == "v2":
        parsed, err = try_parse_review_json_v2(raw)
        if err or parsed is None:
            return GuardrailResult(ok=False, errors=[f"json_parse: {err}"]), err
        return validate_review_output_v2(parsed), None
    if output_format == "v1":
        parsed, err = try_parse_review_json(raw)
        if err or parsed is None:
            return GuardrailResult(ok=False, errors=[f"json_parse: {err}"]), err
        return validate_review_output(parsed), None
    raise ValueError("output_format must be v1 or v2")
