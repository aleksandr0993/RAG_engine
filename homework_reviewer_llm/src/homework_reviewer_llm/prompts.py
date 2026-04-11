"""Шаблоны промптов для SFT и инференса (v1 и v2)."""

from __future__ import annotations

SYSTEM_REVIEWER_RU = """Ты — опытный ревьюер домашних заданий. Твоя задача — дать структурированный разбор работы студента.

Правила:
- Отвечай ТОЛЬКО одним JSON-объектом без пояснений до или после. Без markdown-обёрток.
- Поля JSON: strengths (массив объектов с text, опционально evidence_quote), issues (text, severity: low|medium|high, опционально evidence_quote), recommendations (text, actionable: boolean), score_justification (строка), overall_score (число от 0 до 100), опционально rubric_scores (объект).
- Каждое замечание и сильная сторона по возможности опирай на цитату из работы в evidence_quote.
- Рекомендации должны быть конкретными; помечай actionable=true только если шаг выполним без дополнительных уточнений.
- Не выдумывай фрагменты работы: если цитаты нет, не заполняй evidence_quote.
- Избегай категоричных суждений («полностью неверно», «нигде не сказано») без короткой цитаты из работы в evidence_quote.
- Поле score_justification должно явно связывать оценку с критериями и замечаниями.
"""

SYSTEM_REVIEWER_V2_RU = """Ты — опытный ревьюер домашних заданий. Сформируй ОДИН JSON для двух аудиторий: студент и ревьюер.

Правила:
- Отвечай ТОЛЬКО одним JSON-объектом, без markdown и без текста вне JSON.
- Структура:
  - student_feedback: { summary, strengths[], issues[], recommendations[] } — понятный студенту разбор; recommendations с полем actionable (boolean).
  - reviewer_report: { summary, risk_assessment, score_justification, rubric_scores? } — внутреннее резюме, риски, обоснование оценки.
  - factor_analysis: массив объектов { factor_id, how_used, impact_on_score? }; factor_id ∈ submission | revision_history | student_profile.
  - overall_score: число 0–100.
- Для КАЖДОГО factor_id из множества submission, revision_history, student_profile должен быть ровно один элемент в factor_analysis с объяснением, как фактор повлиял на вывод (если данных нет — явно укажи «данные не предоставлены» и как это ограничивает вывод).
- Опирайся на цитаты из работы в evidence_quote там, где уместно; не придумывай цитаты.
- Избегай категоричных суждений без evidence_quote.
"""


def build_user_prompt_ru(
    *,
    assignment_prompt: str | None,
    rubric_text: str | None,
    submission_text: str,
    revision_history: str | None = None,
    student_profile: str | None = None,
    score_min: float = 0.0,
    score_max: float = 100.0,
    output_format: str = "v1",
) -> str:
    parts: list[str] = []
    if assignment_prompt:
        parts.append("## Формулировка задания\n" + assignment_prompt.strip())
    if rubric_text:
        parts.append("## Критерии оценивания\n" + rubric_text.strip())
    parts.append("## Работа студента (текст и/или код)\n" + submission_text.strip())

    if output_format == "v2":
        if revision_history and revision_history.strip():
            parts.append("## История правок студента\n" + revision_history.strip())
        else:
            parts.append(
                "## История правок студента\n"
                "(не предоставлена — учитывай только текущую версию работы)"
            )
        if student_profile and student_profile.strip():
            parts.append("## Профиль / уровень студента\n" + student_profile.strip())
        else:
            parts.append(
                "## Профиль / уровень студента\n"
                "(не предоставлен — используй нейтральные ожидания)"
            )
        parts.append(
            f"## Задача\nСформируй ответ в JSON формата v2 (student_feedback, reviewer_report, "
            f"factor_analysis, overall_score) по правилам системного сообщения. "
            f"overall_score в [{score_min}, {score_max}]."
        )
    else:
        if revision_history and revision_history.strip():
            parts.append("## История правок студента\n" + revision_history.strip())
        if student_profile and student_profile.strip():
            parts.append("## Профиль / уровень студента\n" + student_profile.strip())
        parts.append(
            f"## Задача\nСформируй ревью в JSON по схеме из системного сообщения (v1). "
            f"overall_score должен быть в диапазоне [{score_min}, {score_max}]."
        )
    return "\n\n".join(parts)


def system_prompt_for_format(output_format: str) -> str:
    if output_format == "v2":
        return SYSTEM_REVIEWER_V2_RU
    if output_format == "v1":
        return SYSTEM_REVIEWER_RU
    raise ValueError("output_format must be v1 or v2")
