"""Формирование примеров для SFT (chat messages), v1 и v2."""

from __future__ import annotations

from homework_reviewer_llm.prompts import build_user_prompt_ru, system_prompt_for_format
from homework_reviewer_llm.schema import (
    FactorAnalysisItem,
    IssueItem,
    NormalizedRecord,
    RecommendationItem,
    ReviewOutput,
    ReviewOutputV2,
    ReviewerReport,
    StrengthItem,
    StudentFeedback,
)


def gold_review_to_output_simple(rec: NormalizedRecord) -> ReviewOutput:
    """
    Превращает текстовое ревью ревьюера в структурированный эталон для обучения (v1 MVP).

    Упрощение: полный текст ревью кладётся в одну рекомендацию; для продакшн-качества
    замените на ручную/полуавтоматическую разметку по полям JSON.
    """
    body = rec.review_text.strip()
    strengths = [
        StrengthItem(
            text=(
                "В работе есть содержательная часть, требующая детального разбора."
                if len(body) > 80
                else "Работа сдана и доступна для ревью."
            )
        )
    ]
    issues = [
        IssueItem(
            text="См. развёрнутый комментарий ревьюера в рекомендациях и обосновании оценки.",
            severity="medium",
        )
    ]
    recommendations = [
        RecommendationItem(
            text=body[:2000] if len(body) <= 2000 else body[:1997] + "...",
            actionable=False,
        )
    ]
    return ReviewOutput(
        strengths=strengths,
        issues=issues,
        recommendations=recommendations,
        score_justification=f"Итоговая оценка согласована с ревьюером: {rec.overall_score}.",
        overall_score=rec.overall_score,
        rubric_scores=rec.rubric_scores,
    )


def gold_review_to_output_v2(rec: NormalizedRecord) -> ReviewOutputV2:
    """Эталон v2: гибрид студент/ревьюер + factor_analysis (MVP-маппинг из review_text)."""
    body = rec.review_text.strip()
    rh = (rec.revision_history or "").strip()
    prof = (rec.student_profile or "").strip()

    student_feedback = StudentFeedback(
        summary=(
            f"Краткий итог по работе: {body[:400]}..."
            if len(body) > 400
            else f"Краткий итог по работе: {body}"
        ),
        strengths=[
            StrengthItem(
                text=(
                    "Есть содержательная часть, требующая разбора по критериям."
                    if len(body) > 80
                    else "Работа доступна для проверки."
                )
            )
        ],
        issues=[
            IssueItem(
                text="Подробности и шаги улучшения см. в рекомендациях ниже.",
                severity="medium",
            )
        ],
        recommendations=[
            RecommendationItem(
                text=body[:2000] if len(body) <= 2000 else body[:1997] + "...",
                actionable=len(body) > 120,
            )
        ],
    )

    reviewer_report = ReviewerReport(
        summary="Внутреннее резюме для ревьюера на основе эталонного текстового ревью.",
        risk_assessment=(
            "Ключевые риски следуют из замечаний ревьюера; проверь полноту решения и соответствие ТЗ."
            if len(body) > 60
            else "Риск: недостаточная детализация в ревью — сверься с первичным текстом работы."
        ),
        score_justification=(
            f"Оценка {rec.overall_score} согласована с ревьюером. Обоснование: {body[:600]}"
            if len(body) > 600
            else f"Оценка {rec.overall_score} согласована с ревьюером. Обоснование: {body}"
        ),
        rubric_scores=rec.rubric_scores,
    )

    factors: list[FactorAnalysisItem] = [
        FactorAnalysisItem(
            factor_id="submission",
            how_used="Текст и код работы — основной источник выводов и замечаний.",
            impact_on_score="Определяет большую часть итоговой оценки.",
        )
    ]
    if rh:
        factors.append(
            FactorAnalysisItem(
                factor_id="revision_history",
                how_used=f"Учтена история правок: {rh[:280]}{'...' if len(rh) > 280 else ''}",
                impact_on_score="Влияет на оценку динамики и полноты исправлений.",
            )
        )
    else:
        factors.append(
            FactorAnalysisItem(
                factor_id="revision_history",
                how_used="История правок не предоставлена; оценка только по текущей версии.",
                impact_on_score="Снижает уверенность в оценке прогресса между итерациями.",
            )
        )
    if prof:
        factors.append(
            FactorAnalysisItem(
                factor_id="student_profile",
                how_used=f"Учтён профиль/уровень: {prof[:280]}{'...' if len(prof) > 280 else ''}",
                impact_on_score="Калибрует ожидания и тон обратной связи.",
            )
        )
    else:
        factors.append(
            FactorAnalysisItem(
                factor_id="student_profile",
                how_used="Профиль студента не предоставлен; использован нейтральный тон и базовые ожидания.",
                impact_on_score="Минимальное влияние на числовую оценку; влияет на формулировки.",
            )
        )

    return ReviewOutputV2(
        student_feedback=student_feedback,
        reviewer_report=reviewer_report,
        factor_analysis=factors,
        overall_score=rec.overall_score,
    )


def record_to_messages(
    rec: NormalizedRecord,
    *,
    output_format: str = "v1",
) -> list[dict[str, str]]:
    user = build_user_prompt_ru(
        assignment_prompt=rec.assignment_prompt,
        rubric_text=rec.rubric_text,
        submission_text=rec.submission_text,
        revision_history=rec.revision_history,
        student_profile=rec.student_profile,
        output_format=output_format,
    )
    system = system_prompt_for_format(output_format)
    if output_format == "v2":
        assistant = gold_review_to_output_v2(rec).model_dump_json(exclude_none=True)
    else:
        assistant = gold_review_to_output_simple(rec).model_dump_json(exclude_none=True)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
        {"role": "assistant", "content": assistant},
    ]


def record_to_sft_dict(rec: NormalizedRecord, *, output_format: str = "v1") -> dict:
    return {
        "id": rec.id,
        "split": rec.split,
        "output_format": output_format,
        "messages": record_to_messages(rec, output_format=output_format),
    }


def load_messages_from_jsonl_line(obj: dict) -> list[dict[str, str]]:
    if "messages" in obj:
        return obj["messages"]
    raise KeyError("expected key 'messages'")
