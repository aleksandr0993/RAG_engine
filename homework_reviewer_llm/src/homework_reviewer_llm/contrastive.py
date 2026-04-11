"""Контрастные примеры для SFT: плохой JSON → исправленный эталон (v1 и v2)."""

from __future__ import annotations

from enum import Enum

from homework_reviewer_llm.prompts import build_user_prompt_ru, system_prompt_for_format
from homework_reviewer_llm.schema import (
    IssueItem,
    NormalizedRecord,
    RecommendationItem,
    ReviewOutput,
    ReviewOutputV2,
    StrengthItem,
    StudentFeedback,
)
from homework_reviewer_llm.sft_format import gold_review_to_output_simple, gold_review_to_output_v2


class ContrastiveKind(str, Enum):
    too_soft = "too_soft"
    no_justification = "no_justification"
    vague_recommendations = "vague_recommendations"


def _base_user_block(rec: NormalizedRecord, *, output_format: str) -> str:
    return build_user_prompt_ru(
        assignment_prompt=rec.assignment_prompt,
        rubric_text=rec.rubric_text,
        submission_text=rec.submission_text,
        revision_history=rec.revision_history,
        student_profile=rec.student_profile,
        output_format=output_format,
    )


def build_bad_review(kind: ContrastiveKind, gold: ReviewOutput) -> ReviewOutput:
    """Синтетически портит эталонный разбор v1."""
    g = gold.model_copy(deep=True)
    if kind == ContrastiveKind.too_soft:
        g.issues = []
        g.overall_score = min(100.0, gold.overall_score + 25.0)
        g.strengths = [
            StrengthItem(text="В целом всё отлично, претензий нет."),
        ]
        g.recommendations = [
            RecommendationItem(text="Так держать.", actionable=False),
        ]
        g.score_justification = "Хорошая работа."
    elif kind == ContrastiveKind.no_justification:
        g.score_justification = "Ок."
    elif kind == ContrastiveKind.vague_recommendations:
        g.recommendations = [
            RecommendationItem(text="Стоит доработать по критериям.", actionable=False),
            RecommendationItem(text="Обратите внимание на качество.", actionable=False),
        ]
    return g


def build_bad_review_v2(kind: ContrastiveKind, gold: ReviewOutputV2) -> ReviewOutputV2:
    """Синтетически портит эталон v2."""
    g = gold.model_copy(deep=True)
    if kind == ContrastiveKind.too_soft:
        g.student_feedback = StudentFeedback(
            summary="Отличная работа, всё хорошо.",
            strengths=[StrengthItem(text="Без замечаний.")],
            issues=[],
            recommendations=[RecommendationItem(text="Продолжай в том же духе.", actionable=False)],
        )
        g.overall_score = min(100.0, gold.overall_score + 20.0)
        g.reviewer_report = g.reviewer_report.model_copy(
            update={
                "score_justification": "Норм.",
                "risk_assessment": "Существенных рисков нет.",
            }
        )
    elif kind == ContrastiveKind.no_justification:
        g.reviewer_report = g.reviewer_report.model_copy(
            update={"score_justification": "Ок."}
        )
    elif kind == ContrastiveKind.vague_recommendations:
        g.student_feedback = g.student_feedback.model_copy(
            update={
                "recommendations": [
                    RecommendationItem(text="Доработать по замечаниям.", actionable=False),
                    RecommendationItem(text="Улучшить качество решения.", actionable=False),
                ]
            }
        )
    return g


REWRITE_USER_SUFFIX = """

## Задача (дополнение)
Ниже приведён ПЛОХОЙ пример ответа в JSON (типичная ошибка). Перепиши в корректный JSON строго по правилам из системного сообщения. Сохрани адекватную оценку и опору на факторы.

### Плохой пример (не копируй)
```json
{BAD_JSON}
```
"""


def messages_rewrite_bad_to_good(
    rec: NormalizedRecord,
    kind: ContrastiveKind,
    *,
    output_format: str,
) -> list[dict[str, str]]:
    system = system_prompt_for_format(output_format)
    if output_format == "v2":
        gold = gold_review_to_output_v2(rec)
        bad = build_bad_review_v2(kind, gold)
        bad_json = bad.model_dump_json(exclude_none=True)
        assistant = gold.model_dump_json(exclude_none=True)
    else:
        gold = gold_review_to_output_simple(rec)
        bad = build_bad_review(kind, gold)
        bad_json = bad.model_dump_json(exclude_none=True)
        assistant = gold.model_dump_json(exclude_none=True)
    user = _base_user_block(rec, output_format=output_format) + REWRITE_USER_SUFFIX.replace(
        "{BAD_JSON}", bad_json
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
        {"role": "assistant", "content": assistant},
    ]


INLINE_WARNING_LINES: dict[ContrastiveKind, str] = {
    ContrastiveKind.too_soft: (
        "Избегай слишком мягкого ревью: нужны конкретные issues при наличии недочётов в работе."
    ),
    ContrastiveKind.no_justification: (
        "Обязательно дай развёрнутое обоснование итоговой оценки (reviewer_report.score_justification для v2)."
    ),
    ContrastiveKind.vague_recommendations: (
        "Рекомендации должны быть actionable там, где это возможно; избегай общих фраз."
    ),
}


def messages_inline_warning(
    rec: NormalizedRecord,
    kind: ContrastiveKind,
    *,
    output_format: str,
) -> list[dict[str, str]]:
    system = system_prompt_for_format(output_format)
    warn = INLINE_WARNING_LINES[kind]
    user = _base_user_block(rec, output_format=output_format) + f"\n\n## Важно\n{warn}\n"
    if output_format == "v2":
        assistant = gold_review_to_output_v2(rec).model_dump_json(exclude_none=True)
    else:
        assistant = gold_review_to_output_simple(rec).model_dump_json(exclude_none=True)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
        {"role": "assistant", "content": assistant},
    ]


def contrastive_record_to_dict(
    rec: NormalizedRecord,
    *,
    mode: str,
    kind: ContrastiveKind,
    output_format: str = "v1",
) -> dict:
    if mode not in ("rewrite_bad", "inline_warning"):
        raise ValueError("mode must be rewrite_bad or inline_warning")
    if output_format not in ("v1", "v2"):
        raise ValueError("output_format must be v1 or v2")
    mid = f"{rec.id}__contrast__{output_format}__{mode}__{kind.value}"
    if mode == "rewrite_bad":
        msgs = messages_rewrite_bad_to_good(rec, kind, output_format=output_format)
    else:
        msgs = messages_inline_warning(rec, kind, output_format=output_format)
    return {
        "id": mid,
        "split": rec.split,
        "output_format": output_format,
        "messages": msgs,
        "contrastive": {"mode": mode, "kind": kind.value},
    }


def parse_contrastive_kinds(spec: str) -> list[ContrastiveKind]:
    if not spec.strip():
        return []
    out: list[ContrastiveKind] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        out.append(ContrastiveKind(part))
    return out
